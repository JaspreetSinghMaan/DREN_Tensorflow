import tensorflow as tf
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.training import moving_averages
import math
from config import Config


MOVING_AVERAGE_DECAY = 0.98
BN_DECAY = MOVING_AVERAGE_DECAY
BN_EPSILON = 0.001
CONV_WEIGHT_DECAY = 0.0001
CONV_WEIGHT_STDDEV = 0.1
RESNET_VARIABLES = 'resnet_variables'
UPDATE_OPS_COLLECTION = 'resnet_update_ops'  # must be grouped with training op
IMAGENET_MEAN_BGR = [103.062623801, 115.902882574, 123.151630838, ]
keep_prob = 0.8
#tf.app.flags.DEFINE_integer('input_size', 224, "input image size")


activation = tf.nn.relu


#logits = inference_small(images,is_training=True)

def whiten(x):
    
    x_mean = tf.reduce_mean(x, axis=[1,2], keep_dims=True)
    x_std = tf.sqrt(tf.reduce_mean(tf.square(x-x_mean), axis=[1,2], keep_dims=True))
    x = (x-x_mean) / x_std
    return x

def inference_small(x,
                    is_training,
                    use_bias=True, 
                    num_classes=10):
    c = Config()
    c['is_training'] = is_training
    c['use_bias'] = use_bias
    c['num_classes'] = num_classes
    return inference_small_config(x, c)
    

def inference_small_config(x, c):
    c['bottleneck'] = False
    c['ksize'] = 3
    c['stride'] = 1
    c['num_blocks']=3
    c['stack_stride'] = 1
    c['padding'] = 'SAME'
    c['reuse'] = None
    c['conv_mode'] = 'normal'
    x = whiten(x)
    with tf.variable_scope('down_scale0',reuse=c['reuse']):
        c['conv_filters_out'] = 16
        c['block_filters_internal'] = 16
        c['num_blocks']=3
        print 'x:',x.get_shape()
        
        x = conv(x, c)
        x = bn(x, c)
        x0 = activation(x)         
        print 'x0:',x0.get_shape()       
        
        x1 = stack(x0, c)
        print 'x1:',x1.get_shape()
    
    with tf.variable_scope('down_scale1',reuse=c['reuse']):
        c['bottleneck'] = False
        c['block_filters_internal'] = 32
        c['num_blocks']=3
        c['stack_stride'] = 2
        
        x1 = stack(x1, c)             
        
        print 'x1:',x1.get_shape()
        
    with tf.variable_scope('down_scale2',reuse=c['reuse']):
        c['bottleneck'] = False
        c['block_filters_internal'] = 64
        c['num_blocks'] = 3
        c['stack_stride'] = 2
        x2 = stack(x1, c)
        #x2 = control_flow_ops.cond(c['is_training'], lambda: tf.nn.dropout(x2,keep_prob),lambda: x2)
        print 'x2:',x2.get_shape()
       
    with tf.variable_scope('output',reuse=c['reuse']):
        c['conv_filters_out'] = c['num_classes']
        c['ksize'] = 1
        c['stride'] = 1
        out = tf.reduce_mean(conv(x2, c),[1,2])
        #out = fc(tf.reduce_mean(x,[1,2]),c)
        print 'out:',out.get_shape() 

    return out



def stack(x, c):
    for n in range(c['num_blocks']):
        s = c['stack_stride'] if n == 0 else 1
        c['block_stride'] = s
        #c['block_filters_internal'] = c['block_filters_internal'] if c['hold']  else 2*c['block_filters_internal']
        with tf.variable_scope('block%d' % (n + 1),reuse=c['reuse']):
            x = block(x, c)
    return x


def block(x, c):
    filters_in = x.get_shape()[-1]

    # Note: filters_out isn't how many filters are outputed. 
    # That is the case when bottleneck=False but when bottleneck is 
    # True, filters_internal*4 filters are outputted. filters_internal is how many filters
    # the 3x3 convs output internally.
    # m = 4 if c['bottleneck'] else 1
    m = 1
    filters_out = m * c['block_filters_internal']

    shortcut = x  # branch 1

    c['conv_filters_out'] = c['block_filters_internal']

    if c['bottleneck']:
        with tf.variable_scope('a',reuse=c['reuse']):
            c['ksize'] = 1
            c['stride'] = c['block_stride']
            x = conv(x, c)
            x = bn(x, c)
            x = activation(x)

        with tf.variable_scope('b',reuse=c['reuse']): 
            c['conv_filters_out'] = filters_out
            c['ksize'] = 3
            x = conv(x, c)
            x = bn(x, c)
            x = activation(x)

        with tf.variable_scope('c',reuse=c['reuse']):
            c['conv_filters_out'] = filters_out
            c['ksize'] = 1
            assert c['stride'] == 1
            x = conv(x, c)
            x = bn(x, c)
    else:
        with tf.variable_scope('A',reuse=c['reuse']):
            c['stride'] = c['block_stride']
            assert c['ksize'] == 3
            x = conv(x, c)
            x = bn(x, c)
            x = activation(x)

        with tf.variable_scope('B',reuse=c['reuse']):
            c['conv_filters_out'] = filters_out
            assert c['ksize'] == 3
            assert c['stride'] == 1
            x = conv(x, c)
            x = bn(x, c)

    with tf.variable_scope('shortcut',reuse=c['reuse']):
        if filters_out != filters_in or c['block_stride'] != 1:
            c['ksize'] = 3+2*(c['block_stride']-1)
            c['stride'] = c['block_stride']
            c['conv_filters_out'] = filters_out
            shortcut = conv(shortcut, c)
            shortcut = bn(shortcut, c)
        else:
            shortcut = crop(shortcut,x) ## cut
            #print shortcut.get_shape()
    return activation(x + shortcut)


def block_pre_act(x, c):
    filters_in = x.get_shape()[-1]

    # Note: filters_out isn't how many filters are outputed. 
    # That is the case when bottleneck=False but when bottleneck is 
    # True, filters_internal*4 filters are outputted. filters_internal is how many filters
    # the 3x3 convs output internally.
    # m = 4 if c['bottleneck'] else 1
    m = 1
    filters_out = m * c['block_filters_internal']

    shortcut = x  # branch 1

    c['conv_filters_out'] = c['block_filters_internal']

    if c['bottleneck']:
        with tf.variable_scope('a',reuse=c['reuse']):
            c['ksize'] = 1
            c['stride'] = c['block_stride']
            x = bn(x, c)
            x = activation(x)
            x = conv(x, c)

        with tf.variable_scope('b',reuse=c['reuse']): 
            c['conv_filters_out'] = filters_out
            c['ksize'] = 3
            x = bn(x, c)
            x = activation(x)
            x = conv(x, c)

        with tf.variable_scope('c',reuse=c['reuse']):
            c['conv_filters_out'] = filters_out
            c['ksize'] = 1
            assert c['stride'] == 1
            x = bn(x, c)
            x = activation(x)
            x = conv(x, c)
    else:
        with tf.variable_scope('A',reuse=c['reuse']):
            c['stride'] = c['block_stride']
            assert c['ksize'] == 3
            x = bn(x, c)
            x = activation(x)
            x = conv(x, c)

        with tf.variable_scope('B',reuse=c['reuse']):
            c['conv_filters_out'] = filters_out
            assert c['ksize'] == 3
            assert c['stride'] == 1
            x = bn(x, c)
            x = activation(x)
            x = conv(x, c)

    with tf.variable_scope('shortcut',reuse=c['reuse']):
        if filters_out != filters_in or c['block_stride'] != 1:
            c['ksize'] = 3+2*(c['block_stride']-1)
            c['stride'] = c['block_stride']
            c['conv_filters_out'] = filters_out
            shortcut = conv(shortcut, c)
            shortcut = bn(shortcut, c)
        else:
            shortcut = crop(shortcut,x) ## cut
            #print shortcut.get_shape()
    return x + shortcut


def bn(x, c):
    x_shape = x.get_shape()
    params_shape = x_shape[-1:]

    axis = list(range(len(x_shape) - 1))

    beta = _get_variable('beta',
                         params_shape,
                         initializer=tf.random_normal_initializer(stddev=0))
    gamma = _get_variable('gamma',
                          params_shape,
                          initializer=tf.random_normal_initializer(stddev=0,mean=1))

    moving_mean = _get_variable('moving_mean',
                                params_shape,
                                initializer=tf.random_normal_initializer(stddev=0),
                                trainable=False)
    moving_variance = _get_variable('moving_variance',
                                    params_shape,
                                    initializer=tf.random_normal_initializer(stddev=0,mean=1),
                                    trainable=False)

    # These ops will only be preformed when training.
    mean, variance = tf.nn.moments(x, axis)
    
    if c['conv_mode']!='normal':
        mean = tf.reshape(mean,[4,-1])
        mean = tf.reduce_mean(mean,0,keep_dims=True)
        mean = tf.reshape(tf.tile(mean,[1,4]),[-1])
        variance = tf.reshape(variance,[4,-1])
        variance = tf.reduce_mean(variance,0,keep_dims=True)
        variance = tf.reshape(tf.tile(variance,[1,4]),[-1])
        
    update_moving_mean = moving_averages.assign_moving_average(moving_mean,
                                                               mean, BN_DECAY)
    update_moving_variance = moving_averages.assign_moving_average(
        moving_variance, variance, BN_DECAY)
    tf.add_to_collection(UPDATE_OPS_COLLECTION, update_moving_mean)
    tf.add_to_collection(UPDATE_OPS_COLLECTION, update_moving_variance)

    mean, variance = control_flow_ops.cond(
        c['is_training'], lambda: (mean, variance),
        lambda: (moving_mean, moving_variance))
    x = tf.nn.batch_normalization(x, mean, variance, beta, gamma, BN_EPSILON)
    #x.set_shape(inputs.get_shape()) ??

    return x




def _get_variable(name,
                  shape,
                  initializer,
                  weight_decay=0.0,
                  dtype='float',
                  trainable=True):
    "A little wrapper around tf.get_variable to do weight decay and add to"
    "resnet collection"
    if weight_decay > 0:
        regularizer = tf.contrib.layers.l2_regularizer(weight_decay)
    else:
        regularizer = None
    with tf.name_scope(name) as scope_name:
        with tf.variable_scope(scope_name) as scope:
        #name=scope + name
        #return tf.get_variable(name,
        #                       shape=shape,
        #                       initializer=initializer,
        #                       regularizer=regularizer,
        #                       trainable=trainable)
        #collections = [tf.GraphKeys.VARIABLES, RESNET_VARIABLES]
            try:
                return tf.get_variable(name,
                                       shape=shape,
                                       initializer=initializer,
                                       #dtype=dtype,
                                       regularizer=regularizer,
                                       #collections=[RESNET_VARIABLES],
                                       trainable=trainable)
            except:
                scope.reuse_variables()
                return tf.get_variable(name,
                                       shape=shape,
                                       initializer=initializer,
                                       #dtype=dtype,
                                       regularizer=regularizer,
                                       #collections=[RESNET_VARIABLES],
                                       trainable=trainable)



def fc(x,c):
    outputs = c['num_classes']
    input_num = x.get_shape()[-1]
    std = 1/math.sqrt(int(input_num))
    shape = [input_num,outputs]

    initializer = tf.random_normal_initializer(stddev=std)
    weights = _get_variable('weights',
                            shape = shape,
                            dtype = 'float',
                            initializer = initializer,
                            weight_decay=CONV_WEIGHT_DECAY)
    #bias_shape = [outputs]
    
    #if c['use_bias']:
        #bias = _get_variable('bias',shape=bias_shape,initializer=tf.random_normal_initializer(stddev=0))
    
    x = tf.contrib.layers.fully_connected(x,outputs)
                                           # weights_initializer=weights)
    return x

def weight_rot(weight, rot):
    if rot == 0:
        return weight
    elif rot ==1:
        return tf.transpose(tf.reverse(weight,[0]),[1,0,2,3])
    elif rot ==2:
        return tf.reverse(tf.reverse(weight,[0]),[1])
    elif rot ==3:
        return tf.transpose(tf.reverse(weight,[1]),[1,0,2,3])

def get_dren_weight(shape, mode):
    if mode == 'decycle' or mode == 'isotonic':
        std=1/math.sqrt(shape[0]*shape[1]*shape[2])/2
    else:
        std=1/math.sqrt(shape[0]*shape[1]*shape[2])
    initializer = tf.random_normal_initializer(stddev=std)  
    if mode == 'normal':
        weight = _get_variable('weights',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        return weight
    elif mode == 'isotonic':
        weight0 = _get_variable('weights_0',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        weight1 = _get_variable('weights_1',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        weight2 = _get_variable('weights_2',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        weight3 = _get_variable('weights_3',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        
        weight_row0 = weight_rot(tf.concat([weight0,weight1,weight2,weight3],3),0)
        weight_row1 = weight_rot(tf.concat([weight3,weight0,weight1,weight2],3),1)
        weight_row2 = weight_rot(tf.concat([weight2,weight3,weight0,weight1],3),2)
        weight_row3 = weight_rot(tf.concat([weight1,weight2,weight3,weight0],3),3)
        return tf.concat([weight_row0,weight_row1,weight_row2,weight_row3],2)
    else:        
        weight = _get_variable('weights',
                                shape=shape,
                                dtype='float',
                                initializer=initializer,
                                weight_decay=CONV_WEIGHT_DECAY)
        weight0=weight_rot(weight, 0)
        weight1=weight_rot(weight, 1)
        weight2=weight_rot(weight, 2)
        weight3=weight_rot(weight, 3)
        #print type(weight0),type(weight1),type(weight2),type(weight3),[weight1,weight1,weight2,weight3]
        if mode == 'cycle':
            return tf.concat([weight0,weight1,weight2,weight3],3)
        elif mode == 'decycle':
            return tf.concat([weight0,weight1,weight2,weight3],2)
def conv(x, c):
    ksize = c['ksize']
    stride = c['stride']
    filters_out = c['conv_filters_out']

    filters_in = x.get_shape()[-1]
    try:
        a=int(filters_in)
    except:
        filters_in=1
    filters_in = int(filters_in)
    filters_out = int(filters_out)
    if c['conv_mode'] == 'normal':
        shape = [ksize, ksize, filters_in, filters_out]
    elif c['conv_mode'] == 'cycle':
        shape = [ksize, ksize, filters_in, filters_out / 4]
    elif c['conv_mode'] == 'isotonic':
        shape = [ksize, ksize, filters_in / 4, filters_out / 4]
    elif c['conv_mode'] == 'decycle':
        shape = [ksize, ksize, filters_in / 4, filters_out]
    weights = get_dren_weight(shape, c['conv_mode'])

    x=tf.nn.conv2d(x, weights, [1, stride, stride, 1], padding=c['padding'])
    x_shape = x.get_shape()
    params_shape = x_shape[-1:]

    if c['use_bias']:
        bias = _get_variable('bias', params_shape,
                             initializer=tf.random_normal_initializer(stddev=0))
        return x + bias
    else:
        return x


def conv_transpose(x, c):
    ksize = c['ksize']
    stride = c['stride']
    filters_out = c['conv_filters_out']
    filters_in = x.get_shape()[-1]
    try:
        a=int(filters_in)
    except:
        filters_in=1
    shape = [ksize, ksize, filters_out, filters_in]

    std=1/math.sqrt(ksize*ksize*int(filters_in))

    initializer = tf.truncated_normal_initializer(stddev=std)

    weights = _get_variable('weights',
                            shape=shape,
                            dtype='float',
                            initializer=initializer,
                            weight_decay=CONV_WEIGHT_DECAY)

    x_shape = x.get_shape()
    
    output_shape = tf.stack([x_shape[0],x_shape[1]*stride,x_shape[2]*stride,int(filters_out)])
    x=tf.nn.conv2d_transpose(x, weights, output_shape, [1, stride, stride, 1]) ##, padding='VALID' ??
    
    if c['use_bias']:
        bias = _get_variable('bias', x.get_shape()[-1:],
                             initializer=tf.random_normal_initializer(stddev=0))
        return x + bias
    else:
        return x

def _max_pool(x, ksize=2, stride=2):
    return tf.nn.max_pool(x,
                          ksize=[1, ksize, ksize, 1],
                          strides=[1, stride,stride, 1],
                          padding='SAME')

def crop(x1,x2):
    # crop x1 into the shape of x2
    x1_shape = x1.get_shape()
    x2_shape = x2.get_shape()
    try:
        border = [int(x1_shape[1] - x2_shape[1]), int(x1_shape[2] - x2_shape[2]), int(x1_shape[3] - x2_shape[3])]
    except:
        border = [2,2,2]
        
    if border[0]>0 and border[1]>0 and border[2]>0:
        return x1[:,border[0]/2:-border[0]/2,border[1]/2:-border[1]/2,border[2]/2:-border[2]/2,:]
    else:
        return x1
    
def crop_concate(x1,x2):
    # crop x1 into the shape of x2, and concated it with x2
    x1_shape = x1.get_shape()
    x2_shape = x2.get_shape()
    #border=(x1_shape[1:-1]-x2_shape[1:-1])/2
    try:
        border = [int(x1_shape[1] - x2_shape[1]), int(x1_shape[2] - x2_shape[2]), int(x1_shape[3] - x2_shape[3])]
    except:
        border = [2,2,2]
    return tf.concat([x2,x1[:,border[0]/2:-border[0]/2,border[1]/2:-border[1]/2,border[2]/2:-border[2]/2,:]],4)


if __name__=='__main__':
    shape= [3,3,1,1]
    a=get_dren_weight(shape,'isotonic')
    #a=get_dren_weight(shape,'cycle')
    config = tf.ConfigProto()
    with tf.Session(config=config) as sess:
        sess.run(tf.global_variables_initializer())
        print tf.transpose(a,[3,2,1,0]).eval()