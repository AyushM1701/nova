"""Step 3: teach Whisper large-v3-turbo to write Hindi and Hinglish in Roman letters and keep its English (a LoRA).

    data/hinglish-train/.venv/Scripts/python helpers/hinglish_train/train.py [--epochs 2] [--batch 8]
    ... train.py --name v2 --splice 0.2 --encoder-layers 4 [--accumulate 2]   (v2: see below)
    ... train.py --convert Oriserve/Whisper-Hindi2Hinglish-Prime   (someone else's model, for evaluate.py)

Nova can keep running beside it: with the decoder alone, batch 4 takes about 2.4 GB of the GPU. Each clip is labelled
with its own language: Whisper's Hindi mode (<|hi|>) learns the Roman output (Nova decodes Hindi clips with language
"hi"), and English clips (<|en|>) keep English as it was, in the same, shuffled batches.
  --splice R          adds R as many clips again, each a Hindi clip and an English one joined (common.splice), in
                      Hindi mode, so the model hears language switch inside a sentence
  --encoder-layers N  also trains the encoder's last N layers (the half that listens), for Indian accents; the lower
                      layers stay frozen, so they keep no activations
Writes $HINGLISH_DIR/[name/]adapter/ (the LoRA), merged/ (full model) and ct2/ (for faster-whisper, used by Nova)."""
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
from common import OUT, splice  # noqa: E402

BASE = "openai/whisper-large-v3-turbo"
LONGEST = 28.0  # seconds: a spliced clip must fit Whisper's 30-second window


def rows(split):
    return [r for r in map(json.loads, (OUT / "roman.jsonl").open(encoding="utf-8")) if r["split"] == split]


def mixed(train_rows, rate):
    """`rate` as many again of Hindi + English pairs, in random order, labelled Hindi (Nova's Roman Hinglish mode)."""
    pools = {lang: [r for r in train_rows if r["lang"] == lang] for lang in ("en", "hi")}
    extra = []
    for _ in range(int(len(train_rows) * rate) if pools["en"] and pools["hi"] else 0):
        a, b = random.choice(pools["hi"]), random.choice(pools["en"])
        if a["seconds"] + b["seconds"] > LONGEST:
            continue
        pair = [a, b] if random.random() < 0.5 else [b, a]
        extra.append({"parts": pair, "lang": "hi", "text": " ".join(p["text"] for p in pair)})
    return extra


def audio_of(r):
    read = lambda one: sf.read(OUT / "clips" / f"{one['id']}.wav", dtype="float32")[0]  # noqa: E731
    return splice(read(r["parts"][0]), read(r["parts"][1])) if "parts" in r else read(r)


def batches(items, size, processor, shuffle):
    order = list(items)
    if shuffle:
        random.shuffle(order)
    for i in range(0, len(order), size):
        chunk = order[i:i + size]
        feats = processor.feature_extractor([audio_of(r) for r in chunk], sampling_rate=16000,
                                            return_tensors="pt").input_features
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


def train(args, out):
    torch.manual_seed(0)
    random.seed(0)
    processor = WhisperProcessor.from_pretrained(BASE)
    model = WhisperForConditionalGeneration.from_pretrained(BASE, torch_dtype=torch.bfloat16).cuda()
    model.config.forced_decoder_ids = None
    model.generation_config.forced_decoder_ids = None
    for p in model.model.encoder.parameters():
        p.requires_grad = False
    targets = r".*decoder.*\.(q_proj|k_proj|v_proj|out_proj|fc1|fc2)"
    if args.encoder_layers:
        total = len(model.model.encoder.layers)
        top = "|".join(str(n) for n in range(total - args.encoder_layers, total))
        targets = f"({targets})|(.*encoder\\.layers\\.({top})\\.self_attn\\.(q_proj|k_proj|v_proj|out_proj))"
    model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none",
                                             target_modules=targets))
    model.print_trainable_parameters()
    train_rows = rows("train")
    extra = mixed(train_rows, args.splice) if args.splice else []
    per_epoch = math.ceil((len(train_rows) + len(extra)) / args.batch)
    steps = args.epochs * math.ceil(per_epoch / args.accumulate)  # optimizer steps
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    warm = min(100, steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (steps - s) / steps))
    print(f"{len(train_rows)} clips, {sum(r['seconds'] for r in train_rows) / 3600:.1f} h, {len(extra)} spliced, "
          f"{steps} steps", flush=True)
    step, seen, t0 = 0, 0, time.time()
    model.train()
    for epoch in range(args.epochs):
        if args.splice and epoch:
            extra = mixed(train_rows, args.splice)  # new pairs each epoch
        for chunk, feats in batches(train_rows + extra, args.batch, processor, shuffle=True):
            labels = labels_for(chunk, processor).cuda()
            feats = feats.cuda().to(torch.bfloat16)
            if args.encoder_layers:  # gradients reach the encoder's top layers; the frozen ones below keep nothing
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    loss = model(input_features=feats, labels=labels).loss
            else:
                with torch.no_grad():  # the encoder listens, untouched
                    heard = model.base_model.model.model.encoder(feats).last_hidden_state
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    loss = model(encoder_outputs=(heard,), labels=labels).loss
            (loss / args.accumulate).backward()
            seen += 1
            if seen % args.accumulate:
                continue
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
                print(f"epoch {epoch + 1} step {step}/{steps} loss {loss.item():.3f} "
                      f"({left:.0f} min left, {torch.cuda.max_memory_allocated() / 2**30:.1f} GB)", flush=True)
        model.save_pretrained(out / "adapter")
    return processor


def convert(src, dest):
    """A Whisper in Hugging Face's format (a local folder) converted for faster-whisper, in float16."""
    # Transformers 5 saves the audio settings as processor_config.json; the converter (and faster-whisper) read
    # preprocessor_config.json, so the base model's own copy goes beside it when missing (same audio settings)
    if not (Path(src) / "preprocessor_config.json").exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download(BASE, "preprocessor_config.json", local_dir=src)
    converter = Path(sys.executable).with_name("ct2-transformers-converter.exe")
    subprocess.run([str(converter), "--model", str(src), "--output_dir", str(dest), "--force",
                    "--quantization", "float16", "--copy_files", "tokenizer.json", "preprocessor_config.json"], check=True)
    print(f"faster-whisper model: {dest}")


def export(processor, out):
    """The adapter folded into the model, then converted for faster-whisper (what Nova runs)."""
    base = WhisperForConditionalGeneration.from_pretrained(BASE, torch_dtype=torch.float16)
    merged = PeftModel.from_pretrained(base, out / "adapter").merge_and_unload()
    merged.save_pretrained(out / "merged")
    processor.save_pretrained(out / "merged")
    convert(out / "merged", out / "ct2")


def fetch_and_convert(repo):
    """Someone else's Hinglish Whisper, for evaluate.py: data/<name>-hf (as published), data/<name>-ct2."""
    from huggingface_hub import snapshot_download
    name = repo.split("/")[-1].lower()
    src = OUT.parent / f"{name}-hf"
    snapshot_download(repo, local_dir=src, allow_patterns=["*.json", "*.safetensors", "*.txt"])
    convert(src, OUT.parent / f"{name}-ct2")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--epochs", type=int, default=2)
    a.add_argument("--batch", type=int, default=8)
    a.add_argument("--accumulate", type=int, default=1)
    a.add_argument("--lr", type=float, default=1e-4)
    a.add_argument("--name", default="")
    a.add_argument("--splice", type=float, default=0.0)
    a.add_argument("--encoder-layers", type=int, default=0)
    a.add_argument("--export-only", action="store_true")
    a.add_argument("--max-steps", type=int, default=0)
    a.add_argument("--convert", default="")
    args = a.parse_args()
    if args.convert:
        sys.exit(fetch_and_convert(args.convert))
    out = OUT / args.name
    processor = WhisperProcessor.from_pretrained(BASE) if args.export_only else train(args, out)
    if processor:
        export(processor, out)
