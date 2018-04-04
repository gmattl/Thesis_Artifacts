import numpy as np
from utilities import *
from sklearn.neighbors import KernelDensity

import sys
sys.path.append('../Thesis_Artifacts')
from utils import *


# Optimal KDE bandwidths that were determined from CV tuning
BANDWIDTHS = {'mnist': 1.20, 'cifar': 0.26}
# TODO: Find bandwidths suitable for our network.


def create_detector(net, x_train, y_train, x_test, y_test, dataset):
    """
    Eftersom adversarial examples ibland kan klassificeras rätt så finns det i det fallet ett set av korrekt
    klassificerade samples. Detta finns inte i novelty detection och kan i värsta fall omöjliggöra metoden.

    :param net:
    :param x_train:
    :param y_train:
    :param x_test:
    :param y_test:
    :param dataset: 'mnist' or 'cifar'
    :return:
    """

    # Assuming test set is not shuffled.
    x_test_closed = x_test[:np.int(len(x_test)/2)]
    x_test_open = x_test[np.int(len(x_test)/2):]

    # Test model.
    preds_closed, _, _ = net.predict(x_test_closed)
    preds_open, _, _ = net.predict(x_test_open)

    # Correctly classified images. There are no correctly classified Omniglot images.
    # TODO: match logits in omniglot to find images with similar response to replace adversarial images in the paper.
    inds_correct = np.where(np.argmax(y_test, 1) == preds_closed)[0]
    x_test_closed = x_test_closed[inds_correct]
    x_test_open = x_test_open[inds_correct]  # Might as well be randomly sampled images of the same amount.
    print("Number of correctly classified images: {}".format(len(x_test_closed)))

    # Gather Bayesian uncertainty scores.
    print('°' * 15 + "Computing Bayesian uncertainty scores")
    x_closed_uncertanties = get_montecarlo_predictions(net, x_test_closed, num_iter=10).var(axis=0).mean(axis=1)
    x_open_uncertanties = get_montecarlo_predictions(net, x_test_open, num_iter=10).var(axis=0).mean(axis=1)

    # Gather Kernel Density Estimates.
    print('°' * 15 + "Gather hidden layer activations")
    x_train_features = get_hidden_representations(net, x_train)
    x_test_closed_features = get_hidden_representations(net, x_test_closed)
    x_test_open_features = get_hidden_representations(net, x_test_open)

    # Train one KDE per class.
    print('°' * 15 + "Training kernel density estimates")
    kernel_dens = {}
    for i in range(y_train.shape[1]):
        class_inds = np.where(y_train.argmax(axis=1) == i)[0]
        kernel_dens[i] = KernelDensity(kernel='gaussian', bandwidth=BANDWIDTHS[dataset])\
            .fit(x_train_features[class_inds])

    # Predict classes.
    print('°' * 15 + "Computing network predictions")
    preds_test_closed, _, _ = net.predict(x_test_closed)
    preds_test_open, _, _ = net.predict(x_test_open)

    # Get density estimates.
    # Calculate scores for each image per predicted label.
    print('°' * 15 + "Computing density estimate scores")
    densities_closed = score_samples(kernel_dens, x_test_closed_features, preds_test_closed)
    densities_open = score_samples(kernel_dens, x_test_open_features, preds_test_open)

    # Z-score the uncertainty and density values.
    print('°' * 15 + "Normalizing values")
    uncerts_closed_z, uncerts_open_z = normalize(x_closed_uncertanties, x_open_uncertanties)
    densities_closed_z, densities_open_z = normalize(densities_closed, densities_open)

    # Build logistic regression detector.
    print('°' * 15 + "Building logistic regression model")
    values, labels, lr = train_logistic_regression(
        densities_pos=densities_open_z,
        densities_neg=densities_closed_z,
        uncerts_pos=uncerts_open_z,
        uncerts_neg=uncerts_closed_z
    )

    # Evaluate detector.
    # Compute logistic regression model predictions.
    print('°' * 15 + 'Predicting values')
    probs = lr.predict_proba(values)[:, 1]

    # Compute ROC and AUC
    n_samples = len(x_test_closed)

    _, _, auc_score = compute_roc(
        probs_neg=probs[:n_samples],
        probs_pos=probs[n_samples:],
        plot=True
    )
    print('Detector ROC-AUC score: %0.4f' % auc_score)

    return kernel_dens, lr