import torch
from torch import nn
from typing import Optional, Tuple, List
from torch.nn import CrossEntropyLoss
import math
import torch.nn.functional as F
from modeling_siglip import SiglipVisionConfig, SiglipVisionModel
from transformers import PreTrainedModel, PretrainedConfig, GenerationConfig, BitsAndBytesConfig
from transformers.modeling_outputs import CausalLMOutput
from dataclasses import dataclass, field

try:
    from apex.normalization import FusedRMSNorm as RMSNorm 
except ModuleNotFoundError:
    print("No fused RMSNorm")
    from rms_norm import RMSNorm

class SwiGLU(nn.Module):
    def __init__(self, d_model, expansion_factor=8/3):
        super(SwiGLU, self).__init__()
        hidden_dim = int(expansion_factor * d_model)
        self.Wg = nn.Linear(d_model, hidden_dim)
        self.W1 = nn.Linear(d_model, hidden_dim)
        self.W2 = nn.Linear(hidden_dim, d_model)

    def forward(self, X):
        # Swish activation: swish(x) = x * sigmoid(x)
        swish_output = X @ self.Wg.weight.T + self.Wg.bias
        swish_activated = swish_output * torch.sigmoid(swish_output)
        
        # Element-wise multiplication with W1
        linear_output = X @ self.W1.weight.T + self.W1.bias
        gated_output = swish_activated * linear_output
        
        # Final projection with W2
        result = gated_output @ self.W2.weight.T + self.W2.bias
        return result

class KVCache():

    def __init__(self) -> None:
        self.key_cache: List[torch.Tensor] = []
        self.value_cache: List[torch.Tensor] = []
    
    def num_items(self) -> int:
        if len(self.key_cache) == 0:
            return 0
        else:
            # The shape of the key_cache is [Batch_Size, Num_Heads_KV, Seq_Len, Head_Dim]
            return self.key_cache[0].shape[-2]

    def update(
        self,
        key_states: torch.Tensor,
        value_states: torch.Tensor,
        layer_idx: int,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        if len(self.key_cache) <= layer_idx:
            # If we never added anything to the KV-Cache of this layer, let's create it.
            self.key_cache.append(key_states)
            self.value_cache.append(value_states)
        else:
            # ... otherwise we concatenate the new keys with the existing ones.
            # each tensor has shape: [Batch_Size, Num_Heads_KV, Seq_Len, Head_Dim]
            self.key_cache[layer_idx] = torch.cat([self.key_cache[layer_idx], key_states], dim=-2)
            self.value_cache[layer_idx] = torch.cat([self.value_cache[layer_idx], value_states], dim=-2)

        # ... and then we return all the existing keys + the new ones.
        return self.key_cache[layer_idx], self.value_cache[layer_idx]

'''
class GemmaConfig(PretrainedConfig):
    model_type = "gemma"

    def __init__(
        self,
        vocab_size,
        hidden_size,
        intermediate_size,
        num_hidden_layers,
        num_attention_heads,
        num_key_value_heads,
        head_dim=256,
        max_position_embeddings=8192,
        rms_norm_eps=1e-6,
        rope_theta=10000.0,
        attention_bias=False,
        attention_dropout=0.0,
        pad_token_id=None,
        **kwargs,
    ):
        super().__init__(**kwargs) 
        self.vocab_size = vocab_size
        self.max_position_embeddings = max_position_embeddings
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.head_dim = head_dim
        self.num_key_value_heads = num_key_value_heads
        self.rms_norm_eps = rms_norm_eps
        self.rope_theta = rope_theta
        self.attention_bias = attention_bias
        self.attention_dropout = attention_dropout
        self.pad_token_id = pad_token_id


class PaliGemmaConfig(PretrainedConfig):
    model_type = "paligemma"

        # WERID BUG WITH PRETRAINED CONFIG WHERE AFTER FIRST INTIALIZATION AND YOU CALL THE PALIGEMMACONFIG AGAIN IT 
        # TRIES TO REINTIIALIZE BUT WITH THE DEFAULT PARAMETERS WHICH IS NONE 

        # TEMP FIX IS TO JUST FEED THE CONFIG MANUALLY 

    def __init__(
        self,
        vision_config={
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
            "attention_bias": False 
        },
        text_config={
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
            "attention_bias": False 
        },
        ignore_index=-100,
        image_token_index=256000,
        vocab_size=257152,
        projection_dim=2048,
        hidden_size=2048,
        pad_token_id=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.ignore_index = ignore_index
        self.image_token_index = image_token_index
        self.vocab_size = vocab_size
        self.projection_dim = projection_dim
        self.hidden_size = hidden_size
        print(hidden_size)
        self.vision_config = SiglipVisionConfig(**vision_config)
        print(text_config)
        self.text_config = GemmaConfig(**text_config, pad_token_id=pad_token_id)
        self.num_image_tokens = (self.vision_config.image_size // self.vision_config.patch_size) ** 2
        self.vision_config.projection_dim = projection_dim
        self.is_encoder_decoder = False
        self.pad_token_id = pad_token_id
'''

class GemmaConfig(PretrainedConfig):
    model_type = "gemma"

    def __init__(
        self,
        vocab_size=257216,
        hidden_size=2048,
        intermediate_size=16384,
        num_hidden_layers=18,
        num_attention_heads=8,
        num_key_value_heads=1,
        head_dim=256,
        max_position_embeddings=512,
        rope_theta=10000,
        attention_bias=False,
        torch_dtype="float32",
        layer_norm_eps=1e-6,
        rms_norm_eps=1e-6,
        attention_dropout = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.num_key_value_heads = num_key_value_heads
        self.head_dim = head_dim
        self.max_position_embeddings = max_position_embeddings
        self.rope_theta = rope_theta
        self.attention_bias = attention_bias
        self.torch_dtype = torch_dtype
        self.layer_norm_eps = layer_norm_eps
        self.rms_norm_eps = rms_norm_eps
        self.attention_dropout = attention_dropout
    
    def to_dict(self):
        """Convert configuration to a dictionary."""
        output = super().to_dict()
        output.update({
            "vocab_size": self.vocab_size,
            "hidden_size": self.hidden_size,
            "intermediate_size": self.intermediate_size,
            "num_hidden_layers": self.num_hidden_layers,
            "num_attention_heads": self.num_attention_heads,
            "num_key_value_heads": self.num_key_value_heads,
            "head_dim": self.head_dim,
            "max_position_embeddings": self.max_position_embeddings,
            "rope_theta": self.rope_theta,
            "attention_bias": self.attention_bias,
            "torch_dtype": self.torch_dtype,
            "layer_norm_eps": self.layer_norm_eps,
            "rms_norm_eps": self.rms_norm_eps,
            "pad_token_id": self.pad_token_id,
            "attention_dropout": self.attention_dropout
        })
        return output

    @classmethod
    def from_dict(cls, config_dict):
        """Instantiate GemmaConfig from a dictionary."""
        return cls(
            vocab_size=config_dict.get("vocab_size", 257216),
            hidden_size=config_dict.get("hidden_size", 2048),
            intermediate_size=config_dict.get("intermediate_size", 16384),
            num_hidden_layers=config_dict.get("num_hidden_layers", 18),
            num_attention_heads=config_dict.get("num_attention_heads", 8),
            num_key_value_heads=config_dict.get("num_key_value_heads", 1),
            head_dim=config_dict.get("head_dim", 256),
            max_position_embeddings=config_dict.get("max_position_embeddings", 512),
            rope_theta=config_dict.get("rope_theta", 10000),
            attention_bias=config_dict.get("attention_bias", False),
            torch_dtype=config_dict.get("torch_dtype", "float32"),
            layer_norm_eps=config_dict.get("layer_norm_eps", 1e-6),
            rms_norm_eps=config_dict.get("rms_norm_eps", 1e-6),
            pad_token_id=config_dict.get("pad_token_id", 0),
            attention_dropout=config_dict.get("attention_dropout", True),
            **config_dict
        )

@dataclass
class PaliGemmaConfig(PretrainedConfig):
    model_type: str = field(default="paligemma")
    vision_config: SiglipVisionConfig = field(default_factory=SiglipVisionConfig)
    text_config: GemmaConfig = field(default_factory=GemmaConfig)
    ignore_index: int = -100
    image_token_index: int = 256000
    vocab_size: int = 257152
    projection_dim: int = 2048
    hidden_size: int = 2048
    pad_token_id: int = 0
    is_encoder_decoder: bool = field(default=False)

    def __post_init__(self):
        super().__init__()

        # If vision_config is a dict, convert it to SiglipVisionConfig
        if isinstance(self.vision_config, dict):
            self.vision_config = SiglipVisionConfig(**self.vision_config)

        # If text_config is a dict, convert it to GemmaConfig
        if isinstance(self.text_config, dict):
            self.text_config = GemmaConfig(**self.text_config)

        # Compute additional attributes
        self.num_image_tokens = (self.vision_config.image_size // self.vision_config.patch_size) ** 2
        self.vision_config.projection_dim = self.projection_dim

    def to_dict(self) -> dict:
        """Convert the configuration to a dictionary."""
        output = super().to_dict()
        output["vision_config"] = self.vision_config.to_dict() if isinstance(self.vision_config, SiglipVisionConfig) else self.vision_config
        output["text_config"] = self.text_config.to_dict() if isinstance(self.text_config, GemmaConfig) else self.text_config
        return output

    @classmethod
    def from_dict(cls, config_dict: dict) -> "PaliGemmaConfig":
        """Instantiate PaliGemmaConfig from a dictionary."""
        vision_config = config_dict.pop("vision_config", {})
        text_config = config_dict.pop("text_config", {})

        return cls(
            vision_config=SiglipVisionConfig.from_dict(vision_config) if isinstance(vision_config, dict) else vision_config,
            text_config=GemmaConfig.from_dict(text_config) if isinstance(text_config, dict) else text_config,
            **config_dict
        )



class GemmaRMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.zeros(dim))

    def _norm(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)

    def forward(self, x):
        output = self._norm(x.float())
        # Llama does x.to(float16) * w whilst Gemma is (x * w).to(float16)
        # See https://github.com/huggingface/transformers/pull/29402
        output = output * (1.0 + self.weight.float())
        return output.type_as(x)

class GemmaRotaryEmbedding(nn.Module):
    def __init__(self, dim, max_position_embeddings=2048, base=10000, device=None):
        super().__init__()

        self.dim = dim # it is set to the head_dim
        self.max_position_embeddings = max_position_embeddings
        self.base = base

        # Calculate the theta according to the formula theta_i = base^(2i/dim) where i = 0, 1, 2, ..., dim // 2
        inv_freq = 1.0 / (self.base ** (torch.arange(0, self.dim, 2, dtype=torch.int64).float() / self.dim))
        self.register_buffer("inv_freq", tensor=inv_freq, persistent=False)

    @torch.no_grad()
    def forward(self, x, position_ids, seq_len=None):
        # x: [bs, num_attention_heads, seq_len, head_size]
        self.inv_freq.to(x.device)
        # Copy the inv_freq tensor for batch in the sequence
        # inv_freq_expanded: [Batch_Size, Head_Dim // 2, 1]
        inv_freq_expanded = self.inv_freq[None, :, None].float().expand(position_ids.shape[0], -1, 1)
        # position_ids_expanded: [Batch_Size, 1, Seq_Len]
        position_ids_expanded = position_ids[:, None, :].float()
        device_type = x.device.type
        device_type = device_type if isinstance(device_type, str) and device_type != "mps" else "cpu"
        with torch.autocast(device_type=device_type, enabled=False):
            # Multiply each theta by the position (which is the argument of the sin and cos functions)
            # freqs: [Batch_Size, Head_Dim // 2, 1] @ [Batch_Size, 1, Seq_Len] --> [Batch_Size, Seq_Len, Head_Dim // 2]
            freqs = (inv_freq_expanded.float() @ position_ids_expanded.float()).transpose(1, 2)
            # emb: [Batch_Size, Seq_Len, Head_Dim]
            emb = torch.cat((freqs, freqs), dim=-1)
            # cos, sin: [Batch_Size, Seq_Len, Head_Dim]
            cos = emb.cos()
            sin = emb.sin()
        return cos.to(dtype=x.dtype), sin.to(dtype=x.dtype)


def rotate_half(x):
    # Build the [-x2, x1, -x4, x3, ...] tensor for the sin part of the positional encoding.
    x1 = x[..., : x.shape[-1] // 2] # Takes the first half of the last dimension
    x2 = x[..., x.shape[-1] // 2 :] # Takes the second half of the last dimension
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(q, k, cos_q, sin_q, cos_k, sin_k, unsqueeze_dim=1):
    cos_q = cos_q.unsqueeze(unsqueeze_dim) # Add the head dimension
    sin_q = sin_q.unsqueeze(unsqueeze_dim) # Add the head dimension
    cos_k = cos_k.unsqueeze(unsqueeze_dim) # Add the head dimension
    sin_k = sin_k.unsqueeze(unsqueeze_dim) # Add the head dimension
    # Apply the formula (34) of the Rotary Positional Encoding paper.
    q_embed = (q * cos_q) + (rotate_half(q) * sin_q)
    k_embed = (k * cos_k) + (rotate_half(k) * sin_k)
    return q_embed, k_embed


class GemmaMLP(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.hidden_size = config.hidden_size
        self.intermediate_size = config.intermediate_size
        self.gate_proj = nn.Linear(self.hidden_size, self.intermediate_size, bias=False)
        self.up_proj = nn.Linear(self.hidden_size, self.intermediate_size, bias=False)
        self.down_proj = nn.Linear(self.intermediate_size, self.hidden_size, bias=False)

    def forward(self, x):
        # Equivalent to:
        # y = self.gate_proj(x) # [Batch_Size, Seq_Len, Hidden_Size] -> [Batch_Size, Seq_Len, Intermediate_Size]
        # y = torch.gelu(y, approximate="tanh") # [Batch_Size, Seq_Len, Intermediate_Size]
        # j = self.up_proj(x) # [Batch_Size, Seq_Len, Hidden_Size] -> [Batch_Size, Seq_Len, Intermediate_Size]
        # z = y * j # [Batch_Size, Seq_Len, Intermediate_Size]
        # z = self.down_proj(z) # [Batch_Size, Seq_Len, Intermediate_Size] -> [Batch_Size, Seq_Len, Hidden_Size]
        return self.down_proj(nn.functional.gelu(self.gate_proj(x), approximate="tanh") * self.up_proj(x))

def repeat_kv(hidden_states: torch.Tensor, n_rep: int) -> torch.Tensor:
    batch, num_key_value_heads, slen, head_dim = hidden_states.shape
    if n_rep == 1:
        return hidden_states
    hidden_states = hidden_states[:, :, None, :, :].expand(batch, num_key_value_heads, n_rep, slen, head_dim)
    return hidden_states.reshape(batch, num_key_value_heads * n_rep, slen, head_dim)

# Our Proposed Differential Attention
class GemmaAttention(nn.Module):
    """Multi-headed attention with Differential Attention"""

    def __init__(self, config: GemmaConfig, layer_idx: Optional[int] = None):
        super().__init__()
        self.config = config
        self.layer_idx = layer_idx

        # Configuration parameters
        self.attention_dropout = config.attention_dropout
        self.hidden_size = config.hidden_size
        self.num_heads = config.num_attention_heads
        self.head_dim = config.head_dim
        self.num_key_value_heads = config.num_key_value_heads
        self.num_key_value_groups = self.num_heads // self.num_key_value_heads
        self.max_position_embeddings = config.max_position_embeddings
        self.rope_theta = config.rope_theta
        self.is_causal = True

        assert self.hidden_size % self.num_heads == 0, (
            f"hidden_size {self.hidden_size} must be divisible by num_heads {self.num_heads}."
        )

        # Projection layers
        self.q_proj = nn.Linear(self.hidden_size, self.num_heads * self.head_dim, bias=config.attention_bias)
        self.k_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=config.attention_bias)
        self.v_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=config.attention_bias)
        self.o_proj = nn.Linear(self.num_heads * self.head_dim, self.hidden_size, bias=config.attention_bias)

        # Rotary embeddings for position encoding
        self.rotary_emb = GemmaRotaryEmbedding(
            self.head_dim,
            max_position_embeddings=self.max_position_embeddings,
            base=self.rope_theta,
        )

        # Differential Attention parameters
        depth = layer_idx - 1 if layer_idx is not None else 0
        self.lambda_init = 0.8 - 0.6 * math.exp(-0.3 * depth)

        std = 0.1  # Standard deviation for initialization
        self.lambda_q1 = nn.Parameter(torch.zeros(self.head_dim, dtype=torch.float32).normal_(mean=0, std=std))
        self.lambda_k1 = nn.Parameter(torch.zeros(self.head_dim, dtype=torch.float32).normal_(mean=0, std=std))
        self.lambda_q2 = nn.Parameter(torch.zeros(self.head_dim, dtype=torch.float32).normal_(mean=0, std=std))
        self.lambda_k2 = nn.Parameter(torch.zeros(self.head_dim, dtype=torch.float32).normal_(mean=0, std=std))

        # RMSNorm for stability
        self.subln = RMSNorm(self.head_dim, eps=1e-5, elementwise_affine=True)

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        kv_cache: Optional[KVCache] = None,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        # Prepare query, key, and value states
        bsz, q_len, _ = hidden_states.size()
        query_states = self.q_proj(hidden_states)
        key_states = self.k_proj(hidden_states)
        value_states = self.v_proj(hidden_states)

        # Reshape and prepare rotary embeddings
        query_states = query_states.view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
        key_states = key_states.view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)
        value_states = value_states.view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)

        cos_q, sin_q = self.rotary_emb(query_states, position_ids, seq_len=None)
        cos_k, sin_k = self.rotary_emb(key_states, position_ids, seq_len=None)
        query_states, key_states = apply_rotary_pos_emb(query_states, key_states, cos_q, sin_q, cos_k, sin_k)

        # Update cached states if available
        if kv_cache is not None:
            key_states, value_states = kv_cache.update(key_states, value_states, self.layer_idx)

        # Expand key/value states to match query heads
        key_states = repeat_kv(key_states, self.num_key_value_groups)
        value_states = repeat_kv(value_states, self.num_key_value_groups)

        # Compute attention weights
        attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) / math.sqrt(self.head_dim)
        attn_weights = torch.nan_to_num(attn_weights)
        if attention_mask is not None:
            attn_weights += attention_mask
        attn_weights = nn.functional.softmax(attn_weights, dim=-1, dtype=torch.float32).type_as(query_states)

        # Differential Attention
        lambda_1 = torch.exp(torch.sum(self.lambda_q1 * self.lambda_k1, dim=-1).float()).type_as(query_states)
        lambda_2 = torch.exp(torch.sum(self.lambda_q2 * self.lambda_k2, dim=-1).float()).type_as(query_states)
        # print(lambda_full)
        # exit()
        lambda_full = lambda_1 - lambda_2 + self.lambda_init

        # Reshape and apply lambda adjustment
        attn_weights = attn_weights.view(bsz, self.num_heads, 1, q_len, -1)
        attn_weights = attn_weights[:, :, 0] - (lambda_full * attn_weights[:, :, 0])

        # Compute attention outputs
        attn_output = torch.matmul(attn_weights, value_states)
        attn_output = self.subln(attn_output)
        attn_output = attn_output * (1 - self.lambda_init)
        attn_output = attn_output.transpose(1, 2).reshape(bsz, q_len, self.num_heads * self.head_dim)

        # Final projection
        attn_output = self.o_proj(attn_output)
        return attn_output, attn_weights

# Original Differential Attention
# class GemmaAttention(nn.Module):

#     def __init__(self, config: GemmaConfig, layer_idx: Optional[int] = None):
#         super().__init__()
#         self.config = config
#         self.layer_idx = layer_idx

#         self.attention_dropout = config.attention_dropout
#         self.hidden_size = config.hidden_size
#         self.num_heads = config.num_attention_heads
#         self.head_dim = config.head_dim
#         self.num_key_value_heads = config.num_key_value_heads
#         self.num_key_value_groups = self.num_heads // self.num_key_value_heads  # n_rep
#         self.max_position_embeddings = config.max_position_embeddings
#         self.rope_theta = config.rope_theta
#         self.is_causal = True

#         assert self.hidden_size % self.num_heads == 0            

#         self.q_proj = nn.Linear(self.hidden_size, self.num_heads * self.head_dim, bias=config.attention_bias)
#         self.k_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=config.attention_bias)
#         self.v_proj = nn.Linear(self.hidden_size, self.num_key_value_heads * self.head_dim, bias=config.attention_bias)
#         self.o_proj = nn.Linear(self.num_heads * self.head_dim, self.hidden_size, bias=config.attention_bias)
#         self.rotary_emb = GemmaRotaryEmbedding(
#             self.head_dim // 2,
#             max_position_embeddings=self.max_position_embeddings,
#             base=self.rope_theta,
#         )

#         '''
#             Differential attention 
#         '''
#         depth = layer_idx - 1
#         self.lambda_init = 0.8 - 0.6 * math.exp(-0.3 * depth)
#         self.lambda_q1 = nn.Parameter(torch.zeros(self.head_dim // 2, dtype=torch.float32).normal_(mean=0,std=0.1))
#         self.lambda_k1 = nn.Parameter(torch.zeros(self.head_dim // 2, dtype=torch.float32).normal_(mean=0,std=0.1))
#         self.lambda_q2 = nn.Parameter(torch.zeros(self.head_dim // 2, dtype=torch.float32).normal_(mean=0,std=0.1))
#         self.lambda_k2 = nn.Parameter(torch.zeros(self.head_dim // 2, dtype=torch.float32).normal_(mean=0,std=0.1))
#         self.subln = RMSNorm(2 * self.head_dim // 2, eps=1e-5, elementwise_affine=True)


#     def forward(
#         self,
#         hidden_states: torch.Tensor,
#         attention_mask: Optional[torch.Tensor] = None,
#         position_ids: Optional[torch.LongTensor] = None,
#         kv_cache: Optional[KVCache] = None,
#         # **kwargs,
#     ) -> Tuple[torch.Tensor, Optional[torch.Tensor], Optional[Tuple[torch.Tensor]]]:
#         bsz, q_len, _ = hidden_states.size() # [Batch_Size, Seq_Len, Hidden_Size]
#         kv_len = q_len
#         # [Batch_Size, Seq_Len, Num_Heads_Q * Head_Dim]
#         query_states = self.q_proj(hidden_states)
#         # [Batch_Size, Seq_Len, Num_Heads_KV * Head_Dim]
#         key_states = self.k_proj(hidden_states)
#         # [Batch_Size, Seq_Len, Num_Heads_KV * Head_Dim]
#         value_states = self.v_proj(hidden_states)

#         '''
#             Differential attention modification here with shape and creating rotary embedding based on query and key sepertely
#         '''
#         # [Batch_Size, Num_Heads_Q, Seq_Len, Head_Dim]
#         query_states = query_states.view(bsz, q_len, 2 * self.num_heads, self.head_dim // 2).transpose(1, 2)
#         # [Batch_Size, Num_Heads_KV, Seq_Len, Head_Dim]
#         key_states = key_states.view(bsz, q_len, 2 * self.num_key_value_heads, self.head_dim // 2).transpose(1, 2)
#         # [Batch_Size, Num_Heads_KV, Seq_Len, Head_Dim]
#         value_states = value_states.view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)

#         # [Batch_Size, Seq_Len, Head_Dim], [Batch_Size, Seq_Len, Head_Dim // 2]
#         cos_q, sin_q = self.rotary_emb(query_states, position_ids, seq_len=None)
#         cos_k, sin_k = self.rotary_emb(key_states, position_ids, seq_len=None)
#         # [Batch_Size, Num_Heads_Q, Seq_Len, Head_Dim], [Batch_Size, Num_Heads_KV, Seq_Len, Head_Dim]
#         query_states, key_states = apply_rotary_pos_emb(query_states, key_states, cos_q, sin_q, cos_k, sin_k)

#         if kv_cache is not None:
#             key_states, value_states = kv_cache.update(key_states, value_states, self.layer_idx)

#         # Repeat the key and values to match the number of heads of the query
#         key_states = repeat_kv(key_states, self.num_key_value_groups)
#         value_states = repeat_kv(value_states, self.num_key_value_groups)

#         """
#             Differential attention
#         """
#         attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) / math.sqrt(self.head_dim)
#         attn_weights = torch.nan_to_num(attn_weights)
#         attn_weights += attention_mask   
#         attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).type_as(
#             attn_weights
#         )

#         lambda_1 = torch.exp(torch.sum(self.lambda_q1 * self.lambda_k1, dim=-1).float()).type_as(query_states)
#         lambda_2 = torch.exp(torch.sum(self.lambda_q2 * self.lambda_k2, dim=-1).float()).type_as(query_states)
#         lambda_full = lambda_1 - lambda_2 + self.lambda_init

#         attn_weights = attn_weights.view(bsz, self.num_heads, 2, q_len, kv_len)
#         attn_weights = attn_weights[:, :, 0] - lambda_full * attn_weights[:, :, 1]
        
#         attn = torch.matmul(attn_weights, value_states)
#         attn = self.subln(attn)
#         attn = attn * (1 - self.lambda_init)
#         attn = attn.transpose(1, 2).reshape(bsz, q_len, self.num_heads * self.head_dim)

#         attn = self.o_proj(attn)
#         return attn, attn_weights
#         '''
#         # Perform the calculation as usual, Q * K^T / sqrt(head_dim). Shape: [Batch_Size, Num_Heads_Q, Seq_Len_Q, Seq_Len_KV]
#         attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) / math.sqrt(self.head_dim)

#         assert attention_mask is not None
#         attn_weights = attn_weights + attention_mask

#         # Apply the softmax
#         # [Batch_Size, Num_Heads_Q, Seq_Len_Q, Seq_Len_KV]
#         attn_weights = nn.functional.softmax(attn_weights, dim=-1, dtype=torch.float32).to(query_states.dtype)
#         # Apply the dropout
#         attn_weights = nn.functional.dropout(attn_weights, p=self.attention_dropout, training=self.training)
#         # Multiply by the values. [Batch_Size, Num_Heads_Q, Seq_Len_Q, Seq_Len_KV] x [Batch_Size, Num_Heads_KV, Seq_Len_KV, Head_Dim] -> [Batch_Size, Num_Heads_Q, Seq_Len_Q, Head_Dim]
#         attn_output = torch.matmul(attn_weights, value_states)

#         if attn_output.size() != (bsz, self.num_heads, q_len, self.head_dim):
#             raise ValueError(
#                 f"`attn_output` should be of size {(bsz, self.num_heads, q_len, self.head_dim)}, but is"
#                 f" {attn_output.size()}"
#             )
#         # Make sure the sequence length is the second dimension. # [Batch_Size, Num_Heads_Q, Seq_Len_Q, Head_Dim] -> [Batch_Size, Seq_Len_Q, Num_Heads_Q, Head_Dim]
#         attn_output = attn_output.transpose(1, 2).contiguous()
#         # Concatenate all the heads together. [Batch_Size, Seq_Len_Q, Num_Heads_Q, Head_Dim] -> [Batch_Size, Seq_Len_Q, Num_Heads_Q * Head_Dim]
#         attn_output = attn_output.view(bsz, q_len, -1)
#         # Multiply by W_o. [Batch_Size, Seq_Len_Q, Hidden_Size]
#         attn_output = self.o_proj(attn_output)

#         return attn_output, attn_weights
#         '''

class GemmaDecoderLayer(nn.Module):

    def __init__(self, config: GemmaConfig, layer_idx: int):
        super().__init__()
        self.hidden_size = config.hidden_size

        self.self_attn = GemmaAttention(config=config, layer_idx=layer_idx)

        self.mlp = GemmaMLP(config)
        self.input_layernorm = GemmaRMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        self.post_attention_layernorm = GemmaRMSNorm(config.hidden_size, eps=config.rms_norm_eps)
        # self.swiglu_layer = SwiGLU(config.hidden_size)

    def forward(
        self,
        hidden_states: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        kv_cache: Optional[KVCache] = None,
    ) -> Tuple[torch.FloatTensor, Optional[Tuple[torch.FloatTensor, torch.FloatTensor]]]:
        residual = hidden_states
        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = self.input_layernorm(hidden_states)

        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states, _, = self.self_attn(
            hidden_states=hidden_states,
            attention_mask=attention_mask,
            position_ids=position_ids,
            kv_cache=kv_cache,
        )

        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = residual + hidden_states # (equation 4)

        # [Batch_Size, Seq_Len, Hidden_Size]
        residual = hidden_states # Y^l
        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = self.post_attention_layernorm(hidden_states) # LN(Y^l)
        # [Batch_Size, Seq_Len, Hidden_Size]

        '''
            Differential attention modification - MLP was replaced with SwiGLU
        '''
        # [Batch_Size, Num_Patches, Embed_Dim] -> [Batch_Size, Num_Patches, Embed_Dim]
        # hidden_states = self.swiglu_layer(hidden_states)
        hidden_states = self.mlp(hidden_states)

        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = residual + hidden_states

        return hidden_states

class GemmaModel(nn.Module):

    def __init__(self, config: GemmaConfig):
        super().__init__()
        self.config = config
        self.padding_idx = config.pad_token_id
        self.vocab_size = config.vocab_size

        self.embed_tokens = nn.Embedding(config.vocab_size, config.hidden_size, self.padding_idx)
        self.layers = nn.ModuleList(
            [GemmaDecoderLayer(config, layer_idx) for layer_idx in range(config.num_hidden_layers)]
        )
        self.norm = GemmaRMSNorm(config.hidden_size, eps=config.rms_norm_eps)

    def get_input_embeddings(self):
        return self.embed_tokens

    # Ignore copy
    def forward(
        self,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        kv_cache: Optional[KVCache] = None,
        # **kwargs,
    ) -> torch.FloatTensor:
        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = inputs_embeds
        # [Batch_Size, Seq_Len, Hidden_Size]
        normalizer = torch.tensor(self.config.hidden_size**0.5, dtype=hidden_states.dtype)
        hidden_states = hidden_states * normalizer

        for decoder_layer in self.layers:
            # [Batch_Size, Seq_Len, Hidden_Size]
            hidden_states = decoder_layer(
                hidden_states,
                attention_mask=attention_mask,
                position_ids=position_ids,
                kv_cache=kv_cache,
            )

        # [Batch_Size, Seq_Len, Hidden_Size]
        hidden_states = self.norm(hidden_states)

        # [Batch_Size, Seq_Len, Hidden_Size]
        return hidden_states

class GemmaForCausalLM(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.model = GemmaModel(config)
        self.vocab_size = config.vocab_size
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False)

    def get_input_embeddings(self):
        return self.model.embed_tokens
    
    def tie_weights(self):
        self.lm_head.weight = self.model.embed_tokens.weight

    def forward(
        self,
        attention_mask: Optional[torch.Tensor] = None,
        position_ids: Optional[torch.LongTensor] = None,
        inputs_embeds: Optional[torch.FloatTensor] = None,
        kv_cache: Optional[KVCache] = None,
        # **kwargs,
    ) -> CausalLMOutput:

        # Forward pass through the base model
        hidden_states = self.model(
            attention_mask=attention_mask,
            position_ids=position_ids,
            inputs_embeds=inputs_embeds,
            kv_cache=kv_cache,
            # **kwargs,
        )

        # Compute logits
        logits = self.lm_head(hidden_states).float()

        # Prepare the output dictionary
        return_data = {
            "logits": logits,
        }

        # Map `kv_cache` to `past_key_values` if cache is used
        if kv_cache is not None:
            # Convert KVCache to list of tuples [(k1, v1), (k2, v2), ...]
            past_key_values = list(zip(kv_cache.key_cache, kv_cache.value_cache))
            return_data["past_key_values"] = past_key_values

        # Return as CausalLMOutput with keyword arguments
        return CausalLMOutput(**return_data)

class PaliGemmaMultiModalProjector(nn.Module):
    def __init__(self, config: PaliGemmaConfig):
        super().__init__()
        self.linear = nn.Linear(config.vision_config.hidden_size, config.vision_config.projection_dim, bias=True)

    def forward(self, image_features):
        # [Batch_Size, Num_Patches, Embed_Dim] -> [Batch_Size, Num_Patches, Projection_Dim]
        hidden_states = self.linear(image_features)
        return hidden_states

class PaliGemmaForConditionalGeneration(PreTrainedModel):
    def __init__(self, config: PaliGemmaConfig, bnb_config: Optional[BitsAndBytesConfig] = None):
        super().__init__(config)
        self.config = config
        self.bnb_config = bnb_config  # Store the bnb_config
        self.vision_tower = SiglipVisionModel(config.vision_config)
        self.multi_modal_projector = PaliGemmaMultiModalProjector(config)
        self.vocab_size = config.vocab_size

        language_model = GemmaForCausalLM(config.text_config)
        self.language_model = language_model

        self.pad_token_id = self.config.pad_token_id if self.config.pad_token_id is not None else -1

        # Initialize generation_config with default parameters
        self.generation_config = GenerationConfig(
            max_length=20,       # Default max_length
            num_beams=1,         # Default number of beams
            early_stopping=False # Default early_stopping
        )
        
        self.loss_f = torch.nn.CrossEntropyLoss(ignore_index=-100)  # -100 is the ignore token

        self.init_weights()

    def tie_weights(self):
        return self.language_model.tie_weights()

    def _merge_input_ids_with_image_features(
        self, image_features: torch.Tensor, inputs_embeds: torch.Tensor, input_ids: torch.Tensor, attention_mask: torch.Tensor, kv_cache: Optional[KVCache] = None
    ):
        _, _, embed_dim = image_features.shape
        batch_size, sequence_length = input_ids.shape
        dtype, device = inputs_embeds.dtype, inputs_embeds.device
        # Shape: [Batch_Size, Seq_Len, Hidden_Size]
        scaled_image_features = image_features / (self.config.hidden_size**0.5)
    
        # Combine the embeddings of the image tokens, the text tokens and mask out all the padding tokens.
        final_embedding = torch.zeros(batch_size, sequence_length, embed_dim, dtype=inputs_embeds.dtype, device=inputs_embeds.device)
        # Shape: [Batch_Size, Seq_Len]. True for text tokens
        text_mask = (input_ids != self.config.image_token_index) & (input_ids != self.pad_token_id)
        # Shape: [Batch_Size, Seq_Len]. True for image tokens
        image_mask = input_ids == self.config.image_token_index
        # Shape: [Batch_Size, Seq_Len]. True for padding tokens
        pad_mask = input_ids == self.pad_token_id

        # We need to expand the masks to the embedding dimension otherwise we can't use them in torch.where
        text_mask_expanded = text_mask.unsqueeze(-1).expand(-1, -1, embed_dim)
        pad_mask_expanded = pad_mask.unsqueeze(-1).expand(-1, -1, embed_dim)
        image_mask_expanded = image_mask.unsqueeze(-1).expand(-1, -1, embed_dim)

        # Add the text embeddings
        final_embedding = torch.where(text_mask_expanded, inputs_embeds, final_embedding)
        # Insert image embeddings. We can't use torch.where because the sequence length of scaled_image_features is not equal to the sequence length of the final embedding
        final_embedding = final_embedding.masked_scatter(image_mask_expanded, scaled_image_features)
        # Zero out padding tokens
        final_embedding = torch.where(pad_mask_expanded, torch.zeros_like(final_embedding), final_embedding)

        #### CREATE THE ATTENTION MASK ####

        dtype, device = inputs_embeds.dtype, inputs_embeds.device
        min_dtype = torch.finfo(dtype).min
        q_len = inputs_embeds.shape[1]
    
        if kv_cache is None or kv_cache.num_items() == 0:
            # Do not mask any token, because we're in the prefill phase
            # This only works when we have no padding
            causal_mask = torch.full(
                (batch_size, q_len, q_len), fill_value=0, dtype=dtype, device=device
            )
        else:
            # Since we are generating tokens, the query must be one single token
            assert q_len == 1
            kv_len = kv_cache.num_items() + q_len
            # Also in this case we don't need to mask anything, since each query should be able to attend all previous tokens. 
            # This only works when we have no padding
            causal_mask = torch.full(
                (batch_size, q_len, kv_len), fill_value=0, dtype=dtype, device=device
            )

        # Add the head dimension
        # [Batch_Size, Q_Len, KV_Len] -> [Batch_Size, Num_Heads_Q, Q_Len, KV_Len]
        causal_mask = causal_mask.unsqueeze(1)

        if kv_cache is not None and kv_cache.num_items() > 0:
            # The position of the query is just the last position
            position_ids = attention_mask.cumsum(-1)[:, -1]
            if position_ids.dim() == 1:
                position_ids = position_ids.unsqueeze(0)
        else:
            # Create a position_ids based on the size of the attention_mask
            # For masked tokens, use the number 1 as position.
            position_ids = (attention_mask.cumsum(-1)).masked_fill_((attention_mask == 0), 1).to(device)

        return final_embedding, causal_mask, position_ids

    def forward(
        self,
        input_ids: torch.LongTensor = None,
        pixel_values: torch.FloatTensor = None,
        attention_mask: Optional[torch.Tensor] = None,
        kv_cache: Optional[KVCache] = None,
        labels: Optional[torch.Tensor] = None,
        **kwargs  # Accept additional keyword arguments
    ) -> CausalLMOutput:

        # Log input shapes
        # print(f"Input IDs shape: {input_ids.shape}")
        # print(f"Attention mask shape: {attention_mask.shape}")

        # 1. Extract the input embeddings
        inputs_embeds = self.language_model.get_input_embeddings()(input_ids)
        
        # If bnb_config is provided, use its compute type for precision
        if self.bnb_config and self.bnb_config.bnb_4bit_compute_dtype:
            inputs_embeds = inputs_embeds.to(dtype=self.bnb_config.bnb_4bit_compute_dtype)

        # 2. Process vision tower for image features
        # Convert pixel_values to match precision if bnb_config is provided
        if self.bnb_config and self.bnb_config.bnb_4bit_compute_dtype:
            pixel_values = pixel_values.to(dtype=self.bnb_config.bnb_4bit_compute_dtype)
        
        selected_image_feature = self.vision_tower(pixel_values)
        image_features = self.multi_modal_projector(selected_image_feature)

        # 3. Merge text and image embeddings
        inputs_embeds, attention_mask, position_ids = self._merge_input_ids_with_image_features(
            image_features, inputs_embeds, input_ids, attention_mask, kv_cache
        )

        # 4. Forward pass through the language model
        outputs = self.language_model(
            attention_mask=attention_mask,
            position_ids=position_ids,
            inputs_embeds=inputs_embeds,
            kv_cache=kv_cache,
            # **kwargs,
        )

        # 5. Compute loss if labels are provided
        loss = None
        if labels is not None:
            # Shift logits and labels for causal language modeling
            shift_logits = outputs.logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = self.loss_f(shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1))
    
        # 6. Adjust output precision if bnb_config is provided
        if self.bnb_config and self.bnb_config.bnb_4bit_compute_dtype:
            outputs.logits = outputs.logits.to(dtype=self.bnb_config.bnb_4bit_compute_dtype)

        return CausalLMOutput(
            loss=loss,
            logits=outputs.logits,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        )