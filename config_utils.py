import json

class VisionConfig:
    def __init__(self, config):
        self.image_size = config.get("image_size")
        self.num_channels = config.get("num_channels")
        self.hidden_size = config.get("hidden_size")
        self.intermediate_size = config.get("intermediate_size")
        self.model_type = config.get("model_type")
        self.num_attention_heads = config.get("num_attention_heads")
        self.num_hidden_layers = config.get("num_hidden_layers")
        self.num_image_tokens = config.get("num_image_tokens")
        self.patch_size = config.get("patch_size")
        self.projection_dim = config.get("projection_dim")
        self.projector_hidden_act = config.get("projector_hidden_act")
        self.vision_use_head = config.get("vision_use_head")
        self.attention_dropout = config.get("attention_dropout")    
        self.rms_norm_eps = config.get("rms_norm_eps")
        self.layer_norm_eps = config.get("layer_norm_eps")


class TextConfig:
    def __init__(self, config):
        self.name_or_path = config.get("_name_or_path")
        self.architectures = config.get("architectures")
        self.bos_token_id = config.get("bos_token_id")
        self.eos_token_id = config.get("eos_token_id")
        self.hidden_size = config.get("hidden_size")
        self.ignore_index = config.get("ignore_index")
        self.image_token_index = config.get("image_token_index")
        self.model_type = config.get("model_type")
        self.pad_token_id = config.get("pad_token_id")
        self.projection_dim = config.get("projection_dim")
        self.torch_dtype = config.get("torch_dtype")
        self.transformers_version = config.get("transformers_version")
        self.vocab_size = config.get("vocab_size")
        self.hidden_size = config.get("hidden_size")
        self.intermediate_size = config.get("intermediate_size")
        self.model_type = config.get("model_type")
        self.num_attention_heads = config.get("num_attention_heads")
        self.num_hidden_layers = config.get("num_hidden_layers")
        self.num_image_tokens = config.get("num_image_tokens")
        self.num_key_value_heads = config.get("num_key_value_heads")
        self.torch_dtype = config.get("torch_dtype")
        self.vocab_size = config.get("vocab_size")
        self.attention_dropout = config.get("attention_dropout")    
        self.rms_norm_eps = config.get("rms_norm_eps")
        self.layer_norm_eps = config.get("layer_norm_eps")
        self.head_dim = self.hidden_size // self.num_attention_heads
        self.max_position_embeddings = config.get("max_position_embeddings")
        self.rope_theta = config.get("rope_theta")
        self.attention_bias = config.get("attention_bias")

class PaliGemmaConfig:
    def __init__(self, config):
        self.name_or_path = config.get("_name_or_path")
        self.architectures = config.get("architectures")
        self.bos_token_id = config.get("bos_token_id")
        self.eos_token_id = config.get("eos_token_id")
        self.hidden_size = config.get("hidden_size")
        self.ignore_index = config.get("ignore_index")
        self.image_token_index = config.get("image_token_index")
        self.model_type = config.get("model_type")
        self.pad_token_id = config.get("pad_token_id")
        self.projection_dim = config.get("projection_dim")
        self.text_config = TextConfig(config.get("text_config", {}))
        self.torch_dtype = config.get("torch_dtype")
        self.transformers_version = config.get("transformers_version")
        self.vision_config = VisionConfig(config.get("vision_config", {}))
        self.vocab_size = config.get("vocab_size")



'''

  "_name_or_path": "final-hf/paligemma-3b-pt-224-main",
  "architectures": [
    "PaliGemmaForConditionalGeneration"
  ],
  "bos_token_id": 2,
  "eos_token_id": 1,
  "hidden_size": 2048,
  "ignore_index": -100,
  "image_token_index": 257152,
  "model_type": "paligemma",
  "pad_token_id": 0,
  "projection_dim": 2048,
  "text_config": {
    "hidden_size": 2048,
    "intermediate_size": 16384,
    "model_type": "gemma",
    "num_attention_heads": 8,
    "num_hidden_layers": 18,
    "num_image_tokens": 256,
    "num_key_value_heads": 1,
    "torch_dtype": "float32",
    "vocab_size": 257216,
    "rms_norm_eps": 1e-6,
    "layer_norm_eps": 1e-6,
    "head_dim": 256,
    "max_position_embeddings": 512,
    "rope_theta": 10000,
    "attention_bias": false 
  },
  "torch_dtype": "float32",
  "transformers_version": "4.41.0.dev0",
  "vision_config": {
    "hidden_size": 1152,
    "intermediate_size": 4304,
    "model_type": "siglip_vision_model",
    "num_attention_heads": 16,
    "num_hidden_layers": 27,
    "num_image_tokens": 256,
    "patch_size": 14,
    "projection_dim": 2048,
    "projector_hidden_act": "gelu_fast",
    "vision_use_head": false,
    "rms_norm_eps": 1e-6,
    "layer_norm_eps": 1e-6
  },
  "vocab_size": 257216
}

'''