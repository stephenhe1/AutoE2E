import os
import subprocess
from dotenv import load_dotenv

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from autoe2e.utils import logger
from .utils import log_user_messages


load_dotenv()

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://ete-litellm.ai-models.vpc-int.res.ibm.com")

# Bounded request settings, applied to every model. Defaults match LLMConfig; a run overrides
# them once via configure_llm() before the first LLM call.
#
# Without an explicit timeout a stalled request blocks forever: confirmed on KEYSTONE_BLOG, where
# call #17 was sent, never returned, and the process sat at 0% CPU for ~41 minutes. The crawl
# budget cannot help, because it is only evaluated at action boundaries. Worst case per call is
# now REQUEST_TIMEOUT_SECONDS x (1 + MAX_RETRIES).
REQUEST_TIMEOUT_SECONDS = 120.0
MAX_RETRIES = 1


def configure_llm(config=None, request_timeout_seconds=None, max_retries=None):
    """Set the bounded request settings for this process. Call once, before any LLM use.

    Models are built lazily, so this must run before the first invocation to take effect; it
    logs the values so a run's log records what bounds were in force. It does not touch
    credential resolution.
    """
    global REQUEST_TIMEOUT_SECONDS, MAX_RETRIES
    if config is not None:
        request_timeout_seconds = getattr(config, 'request_timeout_seconds', None)
        max_retries = getattr(config, 'max_retries', None)
    if request_timeout_seconds is not None:
        REQUEST_TIMEOUT_SECONDS = float(request_timeout_seconds)
    if max_retries is not None:
        MAX_RETRIES = int(max_retries)
    logger.info(
        f'LLM request bounds: request_timeout_seconds={REQUEST_TIMEOUT_SECONDS} '
        f'max_retries={MAX_RETRIES} '
        f'(worst case {REQUEST_TIMEOUT_SECONDS * (1 + MAX_RETRIES)}s per call)')
    return REQUEST_TIMEOUT_SECONDS, MAX_RETRIES


def _get_litellm_api_key():
    key = os.getenv("LITELLM_API_KEY")
    if key:
        return key
    try:
        result = subprocess.run(
            ["op", "read", "op://Employee/API Credentials/credential"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "LITELLM_API_KEY not set and could not read from 1Password. "
            "Either set LITELLM_API_KEY in .env or ensure `op` CLI is authenticated."
        )


_litellm_api_key_cache = None


def _resolve_api_key():
    global _litellm_api_key_cache
    if _litellm_api_key_cache is None:
        _litellm_api_key_cache = _get_litellm_api_key()
    return _litellm_api_key_cache


def create_model_chain(model):
    def invoke_model_chain(system_prompt, user_messages):
        logger.info('Prompt:')
        log_user_messages(user_messages.content)

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            user_messages
        ])
        output_parser = StrOutputParser()

        chain = prompt | model | output_parser

        res = chain.invoke({})
        logger.info("Response:")
        logger.info(res)
        logger.info("")

        return res

    return invoke_model_chain


def _get_sonnet():
    return ChatOpenAI(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=0,
        base_url=LITELLM_BASE_URL,
        api_key=_resolve_api_key(),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def _get_haiku():
    return ChatOpenAI(
        model="aws/claude-haiku-4-5",
        max_tokens=1024,
        temperature=0,
        base_url=LITELLM_BASE_URL,
        api_key=_resolve_api_key(),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


class _LocalEmbeddings:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        return self._model.encode(texts).tolist()

    def embed_query(self, text):
        return self._model.encode(text).tolist()


def _get_openai_embeddings():
    return _LocalEmbeddings()


class _LazyModel:
    def __init__(self, factory):
        self._factory = factory
        self._instance = None

    def _get(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get(), name)


class _LazyChain:
    def __init__(self, model_factory):
        self._chain = None
        self._model_factory = model_factory

    def __call__(self, *args, **kwargs):
        if self._chain is None:
            self._chain = create_model_chain(self._model_factory())
        return self._chain(*args, **kwargs)


sonnet_chain = _LazyChain(_get_sonnet)
haiku_chain = _LazyChain(_get_haiku)

openai_embeddings = _LazyModel(_get_openai_embeddings)
