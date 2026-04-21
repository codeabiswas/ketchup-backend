# Local vLLM Server

This directory contains the standalone vLLM serving surface for Ketchup. It is intentionally separate from the backend API because the backend already owns planner orchestration and tool execution in `agents/planning.py`.

## Why This Layout

The older standalone service from the external `vLLM` folder wrapped `/v1/chat/completions` with its own tool loop. That no longer fits this repo because Ketchup already performs tool-calling at the backend layer. The suitable part to keep here is the raw vLLM OpenAI-compatible server deployment.

## Files

- `vllm/Dockerfile`: builds an image with the model weights baked into `/model-cache`.
- `vllm/entrypoint.sh`: starts `vllm.entrypoints.openai.api_server` with auto tool-calling enabled.
- `vllm/cloudbuild.yaml`: builds and pushes the image to Artifact Registry.

## Local Usage

Build the image with an HF token:

```bash
docker buildx build \
  --file vllm/Dockerfile \
  --secret id=HF_TOKEN,env=HF_TOKEN \
  --tag ketchup-vllm:latest \
  .
```

Run the standalone server:

```bash
docker run --rm -p 8080:8080 \
  -e VLLM_MODEL="Qwen/Qwen3-4B-Instruct-2507" \
  ketchup-vllm:latest
```

Quick checks:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/v1/models
```

## Section 2.6: Pushing the Model to Artifact or Model Registry

This repo now treats the container image as the deployable model artifact.

Build and push with Cloud Build:

```bash
gcloud builds submit \
  --config vllm/cloudbuild.yaml \
  --substitutions _LOCATION=us-central1,_REPO=ketchup-vllm-dev,_NAME=qwen3-4b-2507-vllm
```

That produces an Artifact Registry image suitable for Cloud Run or another serving target. If you later need Vertex AI Model Registry, this image can be referenced from the serving infrastructure, but the artifact push implemented here is Artifact Registry based .

# Test change
- testing a simple flow