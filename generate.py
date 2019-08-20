import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import torch
from PIL import Image
from torch.optim import Adam
from torchvision import transforms

import config
import network
from dataset import preprocess_dataset, VoxCelebDataset

import matplotlib.pyplot as plt


def meta_train(device, dataset_path, continue_id):
    run_start = datetime.now()
    logging.info('===== META-TRAINING =====')
    # GPU / CPU --------------------------------------------------------------------------------------------------------
    if device is not None and device != 'cpu':
        dtype = torch.cuda.FloatTensor
        torch.cuda.set_device(device)
        logging.info(f'Running on GPU: {torch.cuda.current_device()}.')
    else:
        dtype = torch.FloatTensor
        logging.info(f'Running on CPU.')

    # DATASET-----------------------------------------------------------------------------------------------------------
    logging.info(f'Training using dataset located in {dataset_path}')
    dataset = VoxCelebDataset(
        root=dataset_path,
        extension='.vid',
        shuffle=False,
        shuffle_frames=True,
        transform=transforms.Compose([
                transforms.Resize(config.IMAGE_SIZE),
                transforms.CenterCrop(config.IMAGE_SIZE),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    )

    # NETWORK ----------------------------------------------------------------------------------------------------------

    E = network.Embedder().type(dtype)
    G = network.Generator().type(dtype)
    D = network.Discriminator(143000).type(dtype)

    if continue_id is not None:
        E = load_model(E, continue_id)
        G = load_model(G, continue_id)
        D = load_model(D, continue_id)

    optimizer_E_G = Adam(
        params=list(E.parameters()) + list(G.parameters()),
        lr=config.LEARNING_RATE_E_G
    )
    optimizer_D = Adam(
        params=D.parameters(),
        lr=config.LEARNING_RATE_D
    )

    criterion_E_G = network.LossEG(device, feed_forward=True)
    criterion_D = network.LossD(device)

    # TRAINING LOOP ----------------------------------------------------------------------------------------------------
    logging.info(f'Starting training loop. Epochs: {config.EPOCHS} Dataset Size: {len(dataset)}')

    for epoch in range(config.EPOCHS):
        epoch_start = datetime.now()
        batch_durations = []

        E.train()
        G.train()
        D.train()

        for batch_num, (i, video) in enumerate(dataset):
            batch_start = datetime.now()

            # Put one frame aside (frame t)
            t = video.pop()

            # Calculate average encoding vector for video
            e_vectors = []
            for s in video:
                x_s = s['frame'].type(dtype)
                y_s = s['landmarks'].type(dtype)
                e_vectors.append(E(x_s, y_s))
            e_hat = torch.stack(e_vectors).mean(dim=0)

            # Generate frame using landmarks from frame t
            x_t = t['frame'].type(dtype)
            y_t = t['landmarks'].type(dtype)
            x_hat = G(y_t, e_hat)

            # Optimize E_G and D
            r_x_hat, D_act_hat = D(x_hat, y_t, i)
            r_x, D_act = D(x_t, y_t, i)

            optimizer_E_G.zero_grad()
            optimizer_D.zero_grad()

            loss_E_G = criterion_E_G(x_t, x_hat, r_x_hat, e_hat, D.W[:, i], D_act, D_act_hat)
            loss_D = criterion_D(r_x, r_x_hat)
            loss = loss_E_G + loss_D
            loss.backward()

            optimizer_E_G.step()
            optimizer_D.step()

            # Optimize D again
            x_hat = G(y_t, e_hat).detach()
            r_x_hat, D_act_hat = D(x_hat, y_t, i)
            r_x, D_act = D(x_t, y_t, i)

            optimizer_D.zero_grad()
            loss_D = criterion_D(r_x, r_x_hat)
            loss_D.backward()
            optimizer_D.step()

            batch_end = datetime.now()
            batch_durations.append(batch_end - batch_start)
            # SHOW PROGRESS --------------------------------------------------------------------------------------------
            if (batch_num + 1) % 100 == 0 or batch_num == 0:
                avg_time = sum(batch_durations, timedelta(0)) / len(batch_durations)
                logging.info(f'Epoch {epoch+1}: [{batch_num + 1}/{len(dataset)}] | '
                             f'Avg Time: {avg_time} | '
                             f'Loss_E_G = {loss_E_G.item():.4} Loss_D {loss_D.item():.4}')
                logging.debug(f'D(x) = {r_x.item():.4} D(x_hat) = {r_x_hat.item():.4}')

            # SAVE IMAGES ----------------------------------------------------------------------------------------------
            if (batch_num + 1) % 100 == 0:
                if not os.path.isdir(config.GENERATED_DIR):
                    os.makedirs(config.GENERATED_DIR)

                save_image(os.path.join(config.GENERATED_DIR, f'{datetime.now():%Y%m%d_%H%M}_x.png'), x_t)
                save_image(os.path.join(config.GENERATED_DIR, f'{datetime.now():%Y%m%d_%H%M}_x_hat.png'), x_hat)

            if (batch_num + 1) % 2000 == 0:
                save_model(E, device)
                save_model(G, device)
                save_model(D, device)

        # SAVE MODELS --------------------------------------------------------------------------------------------------

        save_model(E, device, run_start)
        save_model(G, device, run_start)
        save_model(D, device, run_start)
        epoch_end = datetime.now()
        if len(batch_durations) != 0:
            logging.info(f'Epoch {epoch+1} finished in {epoch_end - epoch_start}. '
                     f'Average batch time: {sum(batch_durations, timedelta(0)) / len(batch_durations)}')


def save_model(model, gpu, time_for_name=None):
    if time_for_name is None:
        time_for_name = datetime.now()

    model.eval()

    if gpu is not None:
        model.cpu()

    if not os.path.exists(config.MODELS_DIR):
        os.makedirs(config.MODELS_DIR)

    filename = f'{type(model).__name__}_{time_for_name:%Y%m%d_%H%M}.pth'
    torch.save(
        model.state_dict(),
        os.path.join(config.MODELS_DIR, filename)
    )

    if gpu is not None:
        model.cuda()

    logging.info(f'Model saved: {filename}')

    model.train()


def load_model(model, continue_id):
    filename = f'{type(model).__name__}_{continue_id}.pth'
    model.load_state_dict(
        torch.load(
            os.path.join(config.MODELS_DIR,
                         filename)
        )
    )
    return model


def save_image(filename, data):
    data = data.clone().detach().cpu()

    std = np.array([0.229, 0.224, 0.225]).reshape((3, 1, 1))
    mean = np.array([0.485, 0.456, 0.406]).reshape((3, 1, 1))
    img = data.numpy()
    img = ((img * std + mean).transpose(1, 2, 0)*255.0).clip(0, 255).astype("uint8")
    img = Image.fromarray(img)
    img.save(filename)


def imshow(data):
    data = data.clone().detach().cpu()

    std = np.array([0.229, 0.224, 0.225]).reshape((3, 1, 1))
    mean = np.array([0.485, 0.456, 0.406]).reshape((3, 1, 1))
    img = data.numpy()
    img = ((img * std + mean).transpose(1, 2, 0) * 255.0).clip(0, 255).astype("uint8")
    plt.imshow(img)
    plt.show()


def main():
    # ARGUMENTS --------------------------------------------------------------------------------------------------------
    parser = argparse.ArgumentParser(description='Talking Heads')
    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand")

    # ARGUMENTS: DATASET PRE-PROCESSING  -------------------------------------------------------------------------------
    dataset_parser = subparsers.add_parser("dataset", help="Pre-process the dataset for its use.")
    dataset_parser.add_argument("--source", type=str, required=True,
                                help="Path to the source folder where the raw VoxCeleb dataset is located.")
    dataset_parser.add_argument("--output", type=str, required=True,
                                help="Path to the folder where the pre-processed dataset will be stored.")
    dataset_parser.add_argument("--size", type=int, default=0,
                                help="Number of videos from the dataset to process.")
    dataset_parser.add_argument("--ngpu", type=int, default=0,
                                help="Number of GPUs available. Ignore for CPU mode.")
    dataset_parser.add_argument("--overwrite", action="store_true",
                                help="Add this flag to overwrite already pre-processed files. The default functionality"
                                     "is to ignore videos that have already been pre-processed.")
    dataset_parser.add_argument("--rf", type=int, default=1,
                                help="generate random frame from the dataset to process. 0:no, 1:yes")
    # ARGUMENTS: META_TRAINING  ----------------------------------------------------------------------------------------
    train_parser = subparsers.add_parser("meta-train", help="Starts the meta-training process.")
    train_parser.add_argument("--dataset", type=str, required=True,
                              help="Path to the pre-processed dataset.")
    train_parser.add_argument("--ngpu", type=int, default=0,
                              help="Number of GPUs available. Ignore for CPU mode.")
    train_parser.add_argument("--continue_id", type=str, default=None,
                                help="Id of the models to continue training.")

    args = parser.parse_args()

    # LOGGING ----------------------------------------------------------------------------------------------------------

    if not os.path.isdir(config.LOG_DIR):
        os.makedirs(config.LOG_DIR)
    logging.basicConfig(
        level=logging.DEBUG,
        filename=os.path.join(config.LOG_DIR, f'{datetime.now():%Y%m%d}.log'),
        format='[%(asctime)s][%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

    # EXECUTE ----------------------------------------------------------------------------------------------------------
    try:
        if args.subcommand == "meta-train":
            meta_train(
                dataset_path=args.dataset,
                device='cuda:0' if (torch.cuda.is_available() and args.ngpu > 0) else 'cpu',
                continue_id=args.continue_id,
            )
        elif args.subcommand == "dataset":
            preprocess_dataset(
                source=args.source,
                output=args.output,
                device='cuda' if (torch.cuda.is_available() and args.ngpu > 0) else 'cpu',
                size=args.size,
                overwrite=args.overwrite,
                rf=args.rf,
            )
        else:
            print("invalid command")
    except Exception as e:
        logging.error(f'Something went wrong: {e}')
        raise e


if __name__ == '__main__':
    main()
