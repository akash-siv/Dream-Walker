#!/usr/bin/env python3
import argparse
import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.regularizers import l1
from tensorflow.keras.optimizers.legacy import Adam
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelBinarizer
import keras_tuner as kt

# Simple logger so you see epoch metrics at the end of each epoch
def get_logger():
    class BatchLoggerCallback(tf.keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            logs = logs or {}
            print(
                f"Epoch {epoch+1:02d}: "
                f"loss={logs.get('loss',0):.4f}, acc={logs.get('accuracy',0):.4f}; "
                f"val_loss={logs.get('val_loss',0):.4f}, "
                f"val_acc={logs.get('val_accuracy',0):.4f}"
            )
    return BatchLoggerCallback()


def load_data(csv_path):
    df = pd.read_csv(csv_path)
    if 'label' not in df.columns:
        raise ValueError("CSV must contain a 'label' column")
    X = df.drop('label', axis=1).values.astype(np.float32)
    y = df['label'].values
    return X, y


def preprocess(X_train, X_val, y_train, y_val):
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val = scaler.transform(X_val)

    lb = LabelBinarizer()
    y_train = lb.fit_transform(y_train)
    y_val = lb.transform(y_val)

    num_classes = y_train.shape[1]
    return X_train, X_val, y_train, y_val, num_classes


def make_datasets(X_train, y_train, X_val, y_val, batch_size, deterministic):
    train_ds = tf.data.Dataset.from_tensor_slices((X_train, y_train))
    if not deterministic:
        train_ds = train_ds.shuffle(buffer_size=batch_size*4)
    train_ds = train_ds.batch(batch_size)

    val_ds = tf.data.Dataset.from_tensor_slices((X_val, y_val)).batch(batch_size)
    return train_ds, val_ds


def model_builder(hp, input_dim, num_classes):
    # Tune units of first two layers and learning rate
    units1 = hp.Int('units1', min_value=16, max_value=64, step=16)
    units2 = hp.Int('units2', min_value=8, max_value=32, step=8)
    lr = hp.Choice('learning_rate', [1e-2, 1e-3, 1e-4])

    model = Sequential([
        Dense(units1, activation='relu',
              input_shape=(input_dim,),
              activity_regularizer=l1(1e-5)),
        Dense(units2, activation='relu',
              activity_regularizer=l1(1e-5)),
        Dense(10, activation='relu',
              activity_regularizer=l1(1e-5)),
        Dense(5, activation='relu',
              activity_regularizer=l1(1e-5)),
        Dense(num_classes, activation='softmax', name='y_pred')
    ])
    model.compile(
        optimizer=Adam(learning_rate=lr),
        loss='categorical_crossentropy',
        metrics=['accuracy']
    )
    return model


def main():
    parser = argparse.ArgumentParser(
        description="Train a DNN"
    )
    parser.add_argument('--data-path', type=str, required=True,
                        help="Path to CSV with 'label' column + numeric features")
    parser.add_argument('--epochs', type=int, default=30,
                        help="Number of training epochs for final model")
    parser.add_argument('--batch-size', type=int, default=32,
                        help="Batch size for training")
    parser.add_argument('--ensure-determinism', action='store_true',
                        help="Disable dataset shuffling if set")
    parser.add_argument('--tune', action='store_true',
                        help="Run hyperparameter tuning before final training")
    parser.add_argument('--tune-epochs', type=int, default=5,
                        help="Epochs for each trial during tuning")
    parser.add_argument('--max-trials', type=int, default=10,
                        help="Number of hyperparameter trials")
    args = parser.parse_args()

    # Load & split data
    X, y = load_data(args.data_path)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Preprocessing
    X_train, X_val, y_train, y_val, num_classes = preprocess(
        X_train, X_val, y_train, y_val
    )
    train_ds, val_ds = make_datasets(
        X_train, y_train, X_val, y_val,
        batch_size=args.batch_size,
        deterministic=args.ensure_determinism
    )

    # Hyperparameter tuning 
    if args.tune:
        tuner = kt.RandomSearch(
            lambda hp: model_builder(hp, X_train.shape[1], num_classes),
            objective='val_accuracy',
            max_trials=args.max_trials,
            directory='hp_tuning',
            project_name='dense_tuning'
        )
        tuner.search(train_ds,
                     validation_data=val_ds,
                     epochs=args.tune_epochs,
                     verbose=1)
        best_hps = tuner.get_best_hyperparameters(num_trials=1)[0]
        print("Best hyperparameters found:")
        print(f"  units1: {best_hps.get('units1')}")
        print(f"  units2: {best_hps.get('units2')}")
        print(f"  learning_rate: {best_hps.get('learning_rate')}\n")

        # Build final model with best hyperparameters
        model = tuner.hypermodel.build(best_hps)
    else:
        # Default Model
        model = Sequential([
            Dense(30, activation='relu',
                  input_shape=(X_train.shape[1],),
                  activity_regularizer=l1(1e-5)),
            Dense(20, activation='relu',
                  activity_regularizer=l1(1e-5)),
            Dense(10, activation='relu',
                  activity_regularizer=l1(1e-5)),
            Dense(5, activation='relu',
                  activity_regularizer=l1(1e-5)),
            Dense(num_classes, activation='softmax', name='y_pred')
        ])
        model.compile(
            optimizer=Adam(learning_rate=1e-4),
            loss='categorical_crossentropy',
            metrics=['accuracy']
        )

    model.summary()
    model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=args.epochs,
        verbose=0,
        callbacks=[get_logger()]
    )

if __name__ == "__main__":
    main()
