import numpy as np
from copy import deepcopy

import env
from base import BaseEstimator
from layers import FullyConnected, Activation, Dropout
from metrics import get_metric
from optimizers import get_optimizer
from activations import get_activation
from utils import RNG, one_hot_decision_function
from model_selection import TrainTestSplitter


class NNClassifier(BaseEstimator):
    def __init__(self, layers, n_batches=10,
                 loss='categorical_crossentropy', metric='accuracy_score',
                 optimizer='adam', optimizer_params={},
                 shuffle=True, random_seed=None):
        self.layers = layers
        self.n_batches = n_batches # mini-batches will be generated in the stratified manner
        self.loss = loss
        self.metric = metric
        self.optimizer = optimizer
        self.optimizer_params = optimizer_params
        self.shuffle = shuffle
        self.random_seed = random_seed

        self._best_layers = None
        self._n_layers = len(self.layers)
        self._loss = get_metric(self.loss)
        if self.loss == 'categorical_crossentropy':
            self._loss_grad = lambda actual, predicted: -(actual - predicted)
        self._metric = get_metric(self.metric)
        self._optimizer = get_optimizer(self.optimizer, **self.optimizer_params)
        self._tts = TrainTestSplitter(shuffle=self.shuffle, random_seed=self.random_seed)

        self._initialized = False
        self._training = False
        super(NNClassifier, self).__init__(_y_required=True) # TODO: split into multiple NNs later

    def _setup_layers(self, X_shape):
        for layer in self.layers:
            layer.setup_weights(X_shape) # allocate and initialize
            X_shape = layer.shape(prev_shape=X_shape) # forward propagate shape
        self._initialized = True
        if 'verbose' in self.optimizer_params and self.optimizer_params['verbose']:
            print "Total number of parameters: ", self.n_params

    def forward_pass(self, X_batch):
        Z = X_batch
        for layer in self.layers:
            Z = layer.forward_pass(Z)
        return Z

    def update(self, X_batch, y_batch):
        # forward pass
        y_pred = self.forward_pass(X_batch)

        # backward pass
        grad = self._loss_grad(y_batch, y_pred)
        for layer in reversed(self.layers):
            grad = layer.backward_pass(grad)
        return self._loss(y_batch, y_pred)

    def parametric_layers(self):
        for layer in self.layers:
            if hasattr(layer, 'W'):  # TODO: more generic solution
                yield layer

    def batch_iter(self):
        for indices in self._tts.make_k_folds(self._y, n_folds=self.n_batches, stratify=True):
            yield self._X[indices], self._y[indices]

    def _save_best_weights(self):
        self.is_training = False
        self._best_layers = deepcopy(self.layers)
        self.is_training = True

    def _fit(self, X, y, X_val=None, y_val=None):
        for k, v in self.optimizer_params.items(): # TODO: implement set_params for optimizers
            setattr(self._optimizer, k, v)
        for layer in self.layers:
            layer.random_seed = self.random_seed

        if y.ndim == 1:
            y = y[:, np.newaxis]
        if not self._initialized:
            self._setup_layers(X.shape)
        self._X_val = X_val
        self._y_val = y_val
        if 'verbose' in self.optimizer_params and self.optimizer_params['verbose']:
            print "Train on {0} samples, validate on {1} samples\n".format(len(X), len(X_val))
        self.is_training = True
        self._optimizer.optimize(self)
        self.is_training = False

    def validate_proba(self, X=None): # can be called during training
        training_phase = self.is_training
        if training_phase:
            self.is_training = False
        if X is None:
            y_pred = self.forward_pass(self._X)
        else:
            y_pred = self.forward_pass(X)
        if training_phase:
            self.is_training = True
        return y_pred

    def validate(self, X=None):
        y_pred = self.validate_proba(X)
        return one_hot_decision_function(y_pred)

    def predict_proba(self, X):
        # predict on best layers but do not throw away current layers,
        # potentially, they can be improved during further training
        if self._best_layers is not None:
            self.layers, self._best_layers = self._best_layers, self.layers
            y_pred = self.forward_pass(X)
            self.layers, self._best_layers = self._best_layers, self.layers
        else:
            y_pred = self.forward_pass(X)
        return y_pred

    def predict(self, X):
        y_pred = self.predict_proba(X)
        return one_hot_decision_function(y_pred)

    def _serialize(self, params):
        return params

    def _deserialize(self, params):
        return params

    @property
    def n_params(self):
        return sum(layer.n_params for layer in self.layers)

    @property
    def is_training(self):
        return self._training

    @is_training.setter
    def is_training(self, value):
        self._training = value
        for layer in self.layers:
            if hasattr(layer, 'is_training'): # TODO: more generic solution
                layer.is_training = value


if __name__ == '__main__':
    nn = NNClassifier(layers=[
        FullyConnected(512),
        Activation('leaky_relu'),
        Dropout(0.2),
        # FullyConnected(256),
        # Activation('leaky_relu'),
        # Dropout(0.2),
        FullyConnected(10),
        Activation('softmax')
    ], n_batches=10, random_seed=1337, optimizer_params=dict(max_epochs=10, verbose=True))
    from utils.dataset import load_mnist
    from utils import one_hot
    X, y = load_mnist(mode='train', path='../../data/')
    X /= 255.
    train, test = TrainTestSplitter(shuffle=True, random_seed=1337).split(y, train_ratio=0.85)
    y = one_hot(y)
    nn.fit(X[train], y[train], X_val=X[test], y_val=y[test])
    val_pred = nn.predict(X[test])
    print get_metric('accuracy_score')(y[test], val_pred)