# meeting-to-issues (local, free)

Turn meeting transcripts into GitHub Issues using:
- **FastAPI** backend
- **Sentence-Transformers** for embeddings
- **FAISS (local)** vector store
- **Ollama** running phi3:mini
- GitHub REST API for issue creation

.env (server)
GITHUB_TOKEN=ghp_xxx
OLLAMA_BASE=http://127.0.0.1:11434
MODEL_NAME=phi3:mini


.env (frontend)
VITE_API_BASE=http://127.0.0.1:8000



LLM prompt constraints
num_ctx (context window): 4096 tokens
Concatenate system + instructions + retrieved chunks. Keep k small (3–8) to stay under ctx.
num_predict (max new tokens): 800–1200 for detailed lists; 320–600 for concise tasks.



K = number of chunks (pieces of the transcript) retrieved as context for the model. 
Bigger K = more coverage/recall (and a bit slower/more verbose); smaller K = tighter, faster, sometimes misses edge details. 
Typical sweet spot is 4–8.
Number of issues created is driven by the content the model extracts, not by K.



Top-left: the Meeting ID to analyze now. You pick which indexed transcript to run the extractor on.
Bottom (Upload & Index): the Meeting ID to store the next uploaded file under, plus a free-form title. 
After you upload, that ID becomes available in the top field (so you can extract against it). 
It’s not the title; it’s the key used to find the right transcript.




Endpoint design
POST /upload (multipart): file, meeting_id, title -> returns {chunks, tokens_estimate}
POST /tasks/stream (json): {meeting_id, q, k} -> Server-Sent Events (stages: retrieving, ollama, parsing, done)
POST /issues (json): {repo, meeting_id, tasks[]} -> creates issues; returns per-issue status




The chips (action items, decisions, follow-ups blockers, risks, bugs & regressions) sets the query we send to the extractor. The flow is:
You upload a transcript → chunking + indexing.
When you click Extract, the top-K most relevant chunks is retrieved for your current query.
Those chunks go to the model with a prompt that asks it to produce a list of tasks (title, body, labels, etc.).








## Quick start (Windows)


```powershell
# 1) Install Ollama + pull a small model
winget install Ollama.Ollama
ollama pull phi3:mini

# 2) Backend
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt

# 3) Run server (free / local)
$env:OLLAMA_URL="http://127.0.0.1:11434"
$env:OLLAMA_MODEL="phi3:mini"
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

