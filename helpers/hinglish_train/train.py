"""Step 3: teach Whisper large-v3-turbo to write Hindi and Hinglish in Roman letters and keep its English (a LoRA).

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/train.py [--epochs 2] [--batch 8]

Close Nova first: its Whisper holds 2.4 GB of the GPU. Only the decoder (the half that writes) is trained; the
encoder (the half that listens) stays as it is, which keeps this within a 6 GB laptop GPU and keeps its hearing.
Each clip is labelled with its own language: Whisper's Hindi mode (<|hi|>) learns the Roman output (Nova decodes Hindi
clips with language "hi"), and English clips (<|en|>) keep English as it was, in the same, shuffled batches.
Writes $HINGLISH_DIR/adapter/ (the LoRA), merged/ (full model) and ct2/ (for faster-whisper, used by Nova)."""
import argparse
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import WhisperForConditionalGeneration, WhisperProcessor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

BASE = "openai/whisper-large-v3-turbo"


def rows(split):
    return [r for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")) if r["split"] == split]


def batches(items, size, processor, shuffle):
    order = list(items)
    if shuffle:
        random.shuffle(order)
    for i in range(0, len(order), size):
        chunk = order[i:i + size]
        audio = [sf.read(OUT / "clips" / f"{r['id']}.wav", dtype="float32")[0] for r in chunk]
        feats = processor.feature_extractor(audio, sampling_rate=16000, return_tensors="pt").input_features
        yield chunk, feats


def labels_for(chunk, processor):
    tok, ids = processor.tokenizer, []
    for r in chunk:  # <|hi|> or <|en|>, <|transcribe|><|notimestamps|> text <|eot|>: the model puts <|sot|> first itself
        tok.set_prefix_tokens(language="english" if r.get("lang") == "en" else "hindi", task="transcribe",
                              predict_timestamps=False)
        ids.append(tok(r["text"]).input_ids[1:])
    width = max(map(len, ids))
    out = torch.full((len(ids), width), -100, dtype=torch.long)
    for n, seq in enumerate(ids):
        out[n, :len(seq)] = torch.tensor(seq)
    return out


def train(args):
    torch.manual_seed(0)
    random.seed(0)
    processor = WhisperProcessor.from_pretrained(BASE)
    model = WhisperForConditionalGeneration.from_pretrained(BASE, torch_dtype=torch.bfloat16).cuda()
    model.config.forced_decoder_ids = None
    model.generation_config.forced_decoder_ids = None
    for p in model.model.encoder.parameters():
        p.requires_grad = False
    lora = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none",
                      target_modules=r".*decoder.*\.(q_proj|k_proj|v_proj|out_proj|fc1|fc2)")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    train_rows = rows("train")
    steps = args.epochs * math.ceil(len(train_rows) / args.batch)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    warm = min(100, steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (steps - s) / steps))
    print(f"{len(train_rows)} clips, {sum(r['seconds'] for r in train_rows) / 3600:.1f} h, {steps} steps", flush=True)
    step, t0 = 0, time.time()
    model.train()
    for epoch in range(args.epochs):
        for chunk, feats in batches(train_rows, args.batch, processor, shuffle=True):
            labels = labels_for(chunk, processor).cuda()
            with torch.no_grad():  # the encoder listens, untouched
                heard = model.base_model.model.model.encoder(feats.cuda().to(torch.bfloat16)).last_hidden_state
            with torch.autocast("cuda", dtype=torch.bfloat16):
                out = model(encoder_outputs=(heard,), labels=labels)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            if args.max_steps and step >= args.max_steps:  # a trial: memory and speed, nothing saved
                print(f"trial done: {step} steps, {(time.time() - t0) / step:.2f} s a step, "
                      f"{torch.cuda.max_memory_allocated() / 2**30:.1f} GB at most", flush=True)
                return None
            if step % 25 == 0:
                left = (time.time() - t0) / step * (steps - step) / 60
                print(f"epoch {epoch + 1} step {step}/{steps} loss {out.loss.item():.3f} "
                      f"({left:.0f} min left, {torch.cuda.max_memory_allocated() / 2**30:.1f} GB)", flush=True)
        model.save_pretrained(OUT / "adapter")
    return processor


def export(processor):
    """The adapter folded into the model, then converted for faster-whisper (what Nova runs), in float16."""
    base = WhisperForConditionalGeneration.from_pretrained(BASE, torch_dtype=torch.float16)
    merged = PeftModel.from_pretrained(base, OUT / "adapter").merge_and_unload()
    merged.save_pretrained(OUT / "merged")
    processor.save_pretrained(OUT / "merged")
    # Transformers 5 saves the audio settings as processor_config.json; the converter (and faster-whisper) read
    # preprocessor_config.json, so the base model's own copy goes beside it (the audio settings didn't change)
    from huggingface_hub import hf_hub_download
    hf_hub_download(BASE, "preprocessor_config.json", local_dir=OUT / "merged")
    converter = Path(sys.executable).with_name("ct2-transformers-converter.exe")
    subprocess.run([str(converter), "--model", str(OUT / "merged"), "--output_dir", str(OUT / "ct2"), "--force",
                    "--quantization", "float16", "--copy_files", "tokenizer.json", "preprocessor_config.json"], check=True)
    print(f"faster-whisper model: {OUT / 'ct2'}")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--epochs", type=int, default=2)
    a.add_argument("--batch", type=int, default=8)
    a.add_argument("--lr", type=float, default=1e-4)
    a.add_argument("--export-only", action="store_true")
    a.add_argument("--max-steps", type=int, default=0)
    args = a.parse_args()
    processor = WhisperProcessor.from_pretrained(BASE) if args.export_only else train(args)
    if processor:
        export(processor)
