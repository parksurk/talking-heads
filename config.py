# VGG_FACE = r'/home/<user>/Documents/NeuralNetworkModels/vgg_face_dag.pth'
# VGG_FACE = r'/home/<user>/models/vgg_face_dag.pth'
# VGG_FACE = r'/home/antonio/dlc3/models/vgg_face_dag.pth'
# LOG_DIR = r'/ssd256g/k32s56087/logs'
# MODELS_DIR = r'/ssd256g/k32s56087/models'
# GENERATED_DIR = r'/ssd256g/k32s56087/generated_img'

VGG_FACE = r'/home/ubuntu/vgg_models/vgg_face_dag.pth'
LOG_DIR = r'/home/ubuntu/k32s10000/logs'
MODELS_DIR = r'/home/ubuntu/k32s10000/models'
GENERATED_DIR = r'/home/ubuntu/k32s10000/generated_img'

# Dataset parameters
FEATURES_DPI = 100
K = 32

# Training hyperparameters
IMAGE_SIZE = 224
EPOCHS = 100
LEARNING_RATE_E_G = 5e-5
LEARNING_RATE_D = 2e-4
LOSS_VGG_FACE_WEIGHT = 2e-3
LOSS_VGG19_WEIGHT = 1e-2
LOSS_MCH_WEIGHT = 8e1
LOSS_FM_WEIGHT = 1e1
