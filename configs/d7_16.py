
#config a6 is equivalent to a5, except the normalization
import numpy as np
import lasagne as nn
from collections import namedtuple
from functools import partial
import lasagne.layers.dnn as dnn
import lasagne
import theano.tensor as T

import data_transforms
import data_iterators
import pathfinder
import utils
import app
import nn_planet

restart_from_save = None
rng = np.random.RandomState(42)

# transformations
p_transform = {'patch_size': (256, 256),
               'channels': 4,
               'n_labels': 1,
               'n_feat': 64,
               'label_id': 16}


#only lossless augmentations
p_augmentation = {
    'rot90_values': [0,1,2,3],
    'flip': [0, 1]
}



# data preparation function
def data_prep_function_train(x, p_transform=p_transform, p_augmentation=p_augmentation, **kwargs):
    x = np.array(x)
    x = np.swapaxes(x,0,2)
    x = x / 255.
    x = x.astype(np.float32)
    x = data_transforms.lossless(x, p_augmentation, rng)
    return x

def data_prep_function_valid(x, p_transform=p_transform, **kwargs):
    x = np.array(x)
    x = np.swapaxes(x,0,2)
    x = x / 255.
    x = x.astype(np.float32)
    return x

def label_prep_function(label):
    return label[p_transform['label_id']]


# data iterators
# 0.18308259
batch_size = 7
pos_batch_size = 2
neg_batch_size = 5
assert batch_size == (pos_batch_size+neg_batch_size)
nbatches_chunk = 1
chunk_size = batch_size * nbatches_chunk

folds = app.make_stratified_split(no_folds=5)
print len(folds)
train_ids = folds[0] + folds[1] + folds[2] + folds[3]
valid_ids = folds[4]
all_ids = folds[0] + folds[1] + folds[2] + folds[3] + folds[4]

bad_ids = []

train_ids = [x for x in train_ids if x not in bad_ids]
valid_ids = [x for x in valid_ids if x not in bad_ids]

test_ids = np.arange(40669)
test2_ids = np.arange(20522)


train_data_iterator = data_iterators.DiscriminatorDataGenerator(dataset='train-jpg',
                                                    batch_size=batch_size,
                                                    pos_batch_size=pos_batch_size,
                                                    label_id = p_transform['label_id'],
                                                    img_ids = train_ids,
                                                    p_transform=p_transform,
                                                    data_prep_fun = data_prep_function_train,
                                                    label_prep_fun = label_prep_function,
                                                    rng=rng,
                                                    full_batch=True, random=True, infinite=True)

feat_data_iterator = data_iterators.DataGenerator(dataset='train-jpg',
                                                    batch_size=batch_size,
                                                    pos_batch_size=pos_batch_size,
                                                    img_ids = train_ids,
                                                    p_transform=p_transform,
                                                    data_prep_fun = data_prep_function_train,
                                                    label_prep_fun = label_prep_function,
                                                    rng=rng,
                                                    full_batch=False, random=False, infinite=False)

valid_data_iterator = data_iterators.DiscriminatorDataGenerator(dataset='train-jpg',
                                                    batch_size=batch_size,
                                                    pos_batch_size=pos_batch_size,
                                                    label_id = p_transform['label_id'],
                                                    img_ids = valid_ids,
                                                    p_transform=p_transform,
                                                    data_prep_fun = data_prep_function_train,
                                                    label_prep_fun = label_prep_function,
                                                    rng=rng,
                                                    full_batch=True, random=False, infinite=False)

test_data_iterator = data_iterators.DataGenerator(dataset='test-jpg',
                                                    batch_size=batch_size,
                                                    pos_batch_size=pos_batch_size,
                                                    img_ids = test_ids,
                                                    p_transform=p_transform,
                                                    data_prep_fun = data_prep_function_valid,
                                                    label_prep_fun = label_prep_function,
                                                    rng=rng,
                                                    full_batch=False, random=False, infinite=False)

test2_data_iterator = data_iterators.DataGenerator(dataset='test2-jpg',
                                                    batch_size=batch_size,
                                                    pos_batch_size=pos_batch_size,
                                                    img_ids = test2_ids,
                                                    p_transform=p_transform,
                                                    data_prep_fun = data_prep_function_valid,
                                                    label_prep_fun = label_prep_function,
                                                    rng=rng,
                                                    full_batch=False, random=False, infinite=False)



nchunks_per_epoch = train_data_iterator.nsamples / chunk_size
max_nchunks = nchunks_per_epoch * 40


validate_every = int(0.1 * nchunks_per_epoch)
save_every = int(1. * nchunks_per_epoch)

learning_rate_schedule = {
    0: 5e-4,
    int(max_nchunks * 0.4): 2e-4,
    int(max_nchunks * 0.6): 1e-4,
    int(max_nchunks * 0.7): 5e-5,
    int(max_nchunks * 0.8): 2e-5,
    int(max_nchunks * 0.9): 1e-5
}

# model
conv = partial(dnn.Conv2DDNNLayer,
                 filter_size=3,
                 pad='same',
                 W=nn.init.Orthogonal(),
                 nonlinearity=nn.nonlinearities.very_leaky_rectify)

max_pool = partial(dnn.MaxPool2DDNNLayer,
                     pool_size=2)

drop = lasagne.layers.DropoutLayer

dense = partial(lasagne.layers.DenseLayer,
                W=lasagne.init.Orthogonal(),
                nonlinearity=lasagne.nonlinearities.very_leaky_rectify)


def inrn_v2(lin, last_layer_nonlin = lasagne.nonlinearities.rectify):
    n_base_filter = 32

    l1 = conv(lin, n_base_filter, filter_size=1)

    l2 = conv(lin, n_base_filter, filter_size=1)
    l2 = conv(l2, n_base_filter, filter_size=3)

    l3 = conv(lin, n_base_filter, filter_size=1)
    l3 = conv(l3, n_base_filter, filter_size=3)
    l3 = conv(l3, n_base_filter, filter_size=3)

    l = lasagne.layers.ConcatLayer([l1, l2, l3])

    l = conv(l, lin.output_shape[1], filter_size=1)

    l = lasagne.layers.ElemwiseSumLayer([l, lin])

    l = lasagne.layers.NonlinearityLayer(l, nonlinearity= last_layer_nonlin)

    return l


def inrn_v2_red(lin):
    # We want to reduce our total volume /4

    den = 16
    nom2 = 4
    nom3 = 5
    nom4 = 7

    ins = lin.output_shape[1]

    l1 = max_pool(lin)

    l2 = conv(lin, ins // den * nom2, filter_size=3, stride=2)

    l3 = conv(lin, ins // den * nom2, filter_size=1)
    l3 = conv(l3, ins // den * nom3, filter_size=3, stride=2)

    l4 = conv(lin, ins // den * nom2, filter_size=1)
    l4 = conv(l4, ins // den * nom3, filter_size=3)
    l4 = conv(l4, ins // den * nom4, filter_size=3, stride=2)

    l = lasagne.layers.ConcatLayer([l1, l2, l3, l4])

    return l


def feat_red(lin):
    # We want to reduce the feature maps by a factor of 2
    ins = lin.output_shape[1]
    l = conv(lin, ins // 2, filter_size=1)
    return l


def build_model():
    l_in = nn.layers.InputLayer((None, p_transform['channels'],) + p_transform['patch_size']) 
    l_target = nn.layers.InputLayer((None,))

    l = conv(l_in, 64)

    l = inrn_v2_red(l)
    l = inrn_v2(l)

    l = inrn_v2_red(l)
    l = inrn_v2(l)

    l = inrn_v2_red(l)
    l = inrn_v2(l)

    # l = inrn_v2_red(l)
    # l = inrn_v2(l)

    # l = inrn_v2_red(l)
    # l = inrn_v2(l)

    l = drop(l)
    l_neck = nn.layers.GlobalPoolLayer(l)

    # l_out = nn.layers.DenseLayer(l_neck, num_units=p_transform['n_feat'],
    #                              W=nn.init.Orthogonal(),
    #                              nonlinearity=nn.nonlinearities.identity)

    l_out = l_neck


    return namedtuple('Model', ['l_in', 'l_out', 'l_neck', 'l_target'])(l_in, l_out, l_neck, l_target)


def build_objective(model, deterministic=False, epsilon=1.e-7):
    feats= nn.layers.get_output(model.l_out, deterministic=deterministic)
    targets = T.cast(T.flatten(nn.layers.get_output(model.l_target)), 'int32')

    pp = T.log(T.nnet.nnet.sigmoid(T.dot(feats[0],feats[1])))
    p_loss = - 5 * pp
    n_loss = 0
    #two = np.float32()
    for i in range(2,batch_size):
        p0n =  T.log(T.nnet.nnet.sigmoid(-T.dot(feats[0],feats[2])))
        p1n =  T.log(T.nnet.nnet.sigmoid(-T.dot(feats[1],feats[2])))
        n_loss -= p0n / 2. / (batch_size-2.)
        n_loss -= p1n / 2. / (batch_size-2.)

    balance_reg_coeff = 1
    loss = p_loss + n_loss + balance_reg_coeff * (T.exp(p_loss-n_loss)-1)
    return loss

def build_objective2(model, deterministic=False, epsilon=1.e-7):
    feats= nn.layers.get_output(model.l_out, deterministic=deterministic)
    targets = T.cast(T.flatten(nn.layers.get_output(model.l_target)), 'int32')

    pp = T.log(T.nnet.nnet.sigmoid(T.dot(feats[0],feats[1])))
    p_loss = - 5 * pp
    n_loss = 0
    #two = np.float32()
    for i in range(2,batch_size):
        p0n =  T.log(T.nnet.nnet.sigmoid(-T.dot(feats[0],feats[2])))
        p1n =  T.log(T.nnet.nnet.sigmoid(-T.dot(feats[1],feats[2])))
        n_loss -= p0n / 2. / (batch_size-2.)
        n_loss -= p1n / 2. / (batch_size-2.)

    balance_reg_coeff = 1
    loss = p_loss + n_loss + balance_reg_coeff * (T.exp(abs(p_loss-n_loss))-1)
    return p_loss

    # features= nn.layers.get_output(model.l_out, deterministic=deterministic)
    # targets = T.cast(T.flatten(nn.layers.get_output(model.l_target)), 'int32')
    # #feat = T.nnet.nnet.sigmoid(features)
    # feat = features
    # df = T.mean((feat.dimshuffle(['x',0,1]) - feat.dimshuffle([0,'x',1]))**2, axis=2)
    
    # d_p = df[0,1]
    # d_n1 = df[0,2]
    # d_n2 = df[1,2]
    # d_n = T.min(T.stack([d_n1, d_n2]))
    # margin = np.float32(1.)
    # zero = np.float32(0.)
    # triplet_dist_hinge = T.max(T.stack([margin + d_p - d_n, zero]))
    # return d_n

def sigmoid(x):
    s = 1. / (1. + np.exp(-x))
    return s


def score(gts, feats):

    feats = np.vstack(feats)
    gts = np.vstack(gts)
    gts = np.int32(gts)
    
    gt  = gts > 0.5
    gt = gt.flatten()
    non_gt = gts < 0.5
    non_gt = non_gt.flatten()

    preds = []

    for idx, feat in enumerate(feats):
        p_dists = []
        n_dists = []
        for inner_idx, fother in enumerate(feats):
            if inner_idx == idx:
                continue
            dist = sigmoid(np.dot(feat,fother))
            if gt[inner_idx]:
                p_dists.append(dist)
            else:
                n_dists.append(dist)
        if np.mean(p_dists) > np.mean(n_dists):
            preds.append(True)
        else:
            preds.append(False)
    preds = np.array(preds)

    tp = np.sum(np.logical_and(preds,gt))
    fp = np.sum(preds[non_gt])
    fn = np.sum(gt[np.logical_not(preds)])
    tn = np.sum(non_gt[np.logical_not(preds)])

    return [5.*tp/(5*tp+4*fn+fp), tp, fp, fn, tn]


test_score = score


def build_updates(train_loss, model, learning_rate):
    updates = nn.updates.adam(train_loss, nn.layers.get_all_params(model.l_out, trainable=True), learning_rate)
    return updates
