"""Local-model support (fork add-on).

Everything the fork adds for running the reviewer against models served on
this machine (Ollama, LM Studio, oMLX, Splash, mlx-serve, mlx_lm.server,
llama.cpp, vLLM, Jan, LocalAI, or any OpenAI-compatible server) lives in this
package. Upstream files only carry small, clearly marked hook calls into
``backend.localmodels.hooks`` — see LOCAL_MODELS.md for the list — so that
merging new upstream releases into the fork stays conflict-free.
"""
