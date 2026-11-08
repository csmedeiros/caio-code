"""Configuration dataclasses: every tunable number in the agent lives here.

Nothing in the package reads an environment variable or hard-codes a limit;
each layer receives a frozen dataclass from this module. Values are validated
in ``__post_init__`` so a bad configuration fails before the first model call.

Defaults are offline and deterministic: provider ``stub``, char-proxy token
counter, no tracing. A real run opts in explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4
"""Divisor of the thesis proxy ``C = sum_m ceil(|m| / chars_per_token)``.

The same divisor opencode uses for its context estimates, which keeps the
prototype comparable with the tool whose compaction structure it adopts.
"""


@dataclass(frozen=True, slots=True)
class TokenAccountingConfig:
    """How tokens are counted and when a context is considered full."""

    counter: Literal["char_proxy", "tiktoken"] = "char_proxy"
    chars_per_token: int = CHARS_PER_TOKEN
    tiktoken_encoding: str = "o200k_base"

    def __post_init__(self) -> None:
        if self.chars_per_token <= 0:
            msg = f"chars_per_token must be positive, got {self.chars_per_token}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class WindowConfig:
    """The declared model window the policies have to fit into.

    ``tokens`` is the experiment's independent variable: managed arms shape the
    transcript to fit it, and the baseline arm reports the overflow it produces.
    ``context_limit`` is what the provider really accepts; keeping the two apart
    is what allows the baseline to be measured under a forced, smaller window.
    """

    tokens: int = 8_000
    context_limit: int = 128_000
    reserved_output_tokens: int = 4_096
    buffer_tokens: int = 20_000

    def __post_init__(self) -> None:
        for name, value in (
            ("tokens", self.tokens),
            ("context_limit", self.context_limit),
            ("reserved_output_tokens", self.reserved_output_tokens),
            ("buffer_tokens", self.buffer_tokens),
        ):
            if value < 0:
                msg = f"{name} must be non-negative, got {value}"
                raise ValueError(msg)
        if self.tokens <= 0:
            msg = f"window tokens must be positive, got {self.tokens}"
            raise ValueError(msg)
        if self.tokens > self.context_limit:
            msg = f"window tokens {self.tokens} exceed context limit {self.context_limit}"
            raise ValueError(msg)

    @property
    def compaction_trigger_tokens(self) -> int:
        """Point at which auto-compaction fires, as in opencode: limit - max(output, buffer)."""
        return max(0, self.context_limit - max(self.reserved_output_tokens, self.buffer_tokens))


# ---------------------------------------------------------------------------
# Context policies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlidingWindowConfig:
    """Keep the newest contiguous tail that fits the window."""

    keep_recent_messages: int = 2

    def __post_init__(self) -> None:
        if self.keep_recent_messages < 0:
            msg = f"keep_recent_messages must be non-negative, got {self.keep_recent_messages}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Relevance-scored retention: a non-contiguous subset of the transcript.

    ``scorer`` decides who assigns the relevance: ``lexical`` is deterministic and
    free, ``model`` asks the auxiliary chat model for JSON scores, and
    ``decision`` asks the TypeSafe decision model one yes/no question per message
    and uses the probability of yes. The three are interchangeable because the
    policy only ever sees numbers.
    """

    keep_recent_messages: int = 4
    scorer: Literal["lexical", "model", "decision"] = "lexical"
    top_k_floor: int = 1

    def __post_init__(self) -> None:
        if self.keep_recent_messages < 0:
            msg = f"keep_recent_messages must be non-negative, got {self.keep_recent_messages}"
            raise ValueError(msg)
        if self.top_k_floor < 0:
            msg = f"top_k_floor must be non-negative, got {self.top_k_floor}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CompactionConfig:
    """Anchored compaction, structurally the one opencode ships.

    ``keep_tokens`` is the verbatim tail that survives a compaction; everything
    older is folded into the anchored summary. ``tool_result_char_cap`` bounds a
    single tool result inside the text handed to the summarizer, and
    ``head_char_cap`` bounds that text as a whole: a session with 160 KB of head
    makes the summary call itself the most expensive request of the run and can
    time out, so the oldest part of the head is dropped with an explicit marker.
    """

    keep_tokens: int = 8_000
    summary_max_tokens: int = 4_096
    tool_result_char_cap: int = 2_000
    head_char_cap: int = 100_000
    summarizer_model: str | None = None
    auto: bool = True

    def __post_init__(self) -> None:
        if self.keep_tokens < 0:
            msg = f"keep_tokens must be non-negative, got {self.keep_tokens}"
            raise ValueError(msg)
        if self.summary_max_tokens <= 0:
            msg = f"summary_max_tokens must be positive, got {self.summary_max_tokens}"
            raise ValueError(msg)
        if self.tool_result_char_cap <= 0:
            msg = f"tool_result_char_cap must be positive, got {self.tool_result_char_cap}"
            raise ValueError(msg)
        if self.head_char_cap <= 0:
            msg = f"head_char_cap must be positive, got {self.head_char_cap}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ToolOutputConfig:
    """Caps applied to tool results before they ever reach the model.

    Line and byte ceilings are opencode's (2000 lines / 51200 bytes); the
    head/tail split keeps the beginning of a file and its most recent lines,
    which is where the answer usually is.
    """

    max_lines: int = 2_000
    max_bytes: int = 51_200
    max_chars_in_summary: int = 2_000
    placeholder: str = "[truncated]"

    def __post_init__(self) -> None:
        for name, value in (
            ("max_lines", self.max_lines),
            ("max_bytes", self.max_bytes),
            ("max_chars_in_summary", self.max_chars_in_summary),
        ):
            if value <= 0:
                msg = f"{name} must be positive, got {value}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """The control arm: no management at all.

    ``enforce_window`` decides what an overflow means. When false the run is
    sent to the model as-is and the overflow is only measured (cost arm). When
    true the harness refuses the call and records a ``ContextOverflowError``
    (failure arm), which is the honest outcome of running out of window.
    """

    enforce_window: bool = False


DEFAULT_DECISION_MODEL = "jev-latest"
DEFAULT_TYPESAFE_BASE_URL = "https://api.typesafe.ai"
"""Root URL of the decision-model API; requests go to ``/v1/systemone`` beneath it."""


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    """The decision model (TypeSafe Jev) and how the agent questions it.

    A decision model answers typed questions with probabilities. The agent uses
    it where a calibrated judgement beats a generated sentence: scoring the
    relevance of a message for the selection policy, and judging whether a tool
    call is a risky or stuck repeat.

    ``state_message_char_cap`` bounds each message placed in the state: relevance
    does not need a 2,000-line file dump, and sending one would make the scorer
    cost more than the tokens it saves. ``questions_per_request`` bounds how many
    messages are judged per call, since the state is resent with every request.
    """

    provider: Literal["stub", "typesafe"] = "stub"
    model: str = DEFAULT_DECISION_MODEL
    base_url: str = DEFAULT_TYPESAFE_BASE_URL
    timeout_seconds: float = 60.0
    state_message_char_cap: int = 600
    questions_per_request: int = 40
    relevance_threshold: float = 0.5
    risk_threshold: float = 0.5

    def __post_init__(self) -> None:
        if not self.model.strip():
            msg = "decision model must not be empty"
            raise ValueError(msg)
        if self.timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {self.timeout_seconds}"
            raise ValueError(msg)
        if self.state_message_char_cap <= 0:
            msg = f"state_message_char_cap must be positive, got {self.state_message_char_cap}"
            raise ValueError(msg)
        if self.questions_per_request <= 0:
            msg = f"questions_per_request must be positive, got {self.questions_per_request}"
            raise ValueError(msg)
        for name, value in (
            ("relevance_threshold", self.relevance_threshold),
            ("risk_threshold", self.risk_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                msg = f"{name} must be within [0, 1], got {value}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GuardrailConfig:
    """Loop detection: the same tool call repeated with the same arguments."""

    max_repeats: int = 3
    window_messages: int = 12

    def __post_init__(self) -> None:
        if self.max_repeats < 2:
            msg = f"max_repeats must be at least 2, got {self.max_repeats}"
            raise ValueError(msg)
        if self.window_messages < self.max_repeats:
            msg = "window_messages must be at least max_repeats"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

DEFAULT_AGENT_MODEL = "qwen3.8-max"
DEFAULT_AUX_MODEL = "qwen3.8-flash"


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Which endpoint answers the agent loop and which answers auxiliary calls.

    ``provider='stub'`` is the offline default: deterministic, no key, no
    network, and the only provider tests and CI are allowed to use.

    TypeSafe is deliberately absent: Jev is a decision model that answers typed
    questions with probabilities, not a chat model. It lives in
    :class:`DecisionConfig` and is reached through the decision port.
    """

    provider: Literal["stub", "openai_compatible"] = "stub"
    model: str = DEFAULT_AGENT_MODEL
    aux_provider: Literal["stub", "openai_compatible"] = "stub"
    aux_model: str = DEFAULT_AUX_MODEL
    temperature: float = 0.0
    max_output_tokens: int = 4_096
    timeout_seconds: float = 120.0
    aux_timeout_seconds: float = 300.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.model:
            msg = "model must not be empty"
            raise ValueError(msg)
        if self.max_output_tokens <= 0:
            msg = f"max_output_tokens must be positive, got {self.max_output_tokens}"
            raise ValueError(msg)
        if self.timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {self.timeout_seconds}"
            raise ValueError(msg)
        if self.aux_timeout_seconds <= 0:
            msg = f"aux_timeout_seconds must be positive, got {self.aux_timeout_seconds}"
            raise ValueError(msg)
        if self.max_retries < 0:
            msg = f"max_retries must be non-negative, got {self.max_retries}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """Credentials and base URLs, read once from the environment."""

    openai_api_key: str = ""
    openai_base_url: str = ""
    typesafe_api_key: str = ""
    typesafe_base_url: str = ""
    """Optional override; the decision-model client defaults to the public API."""
    langsmith_api_key: str = ""
    langsmith_project: str = "caio-code"

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langsmith_api_key)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per million tokens, split by cache hit."""

    model: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        for name, value in (
            ("input_per_million", self.input_per_million),
            ("cached_input_per_million", self.cached_input_per_million),
            ("output_per_million", self.output_per_million),
        ):
            if value < 0:
                msg = f"{name} must be non-negative, got {value}"
                raise ValueError(msg)


# Public list prices of the models the experiment may run, in USD per million
# tokens. Unknown models fall back to ``FALLBACK_PRICE`` so a missing entry
# degrades into an estimate instead of a crash mid-experiment.
PRICE_SHEET: tuple[ModelPrice, ...] = (
    ModelPrice("qwen3.8-max", Decimal("1.60"), Decimal("0.64"), Decimal("6.40")),
    ModelPrice("qwen3.8-flash", Decimal("0.15"), Decimal("0.06"), Decimal("0.60")),
    ModelPrice("qwen3.7-max", Decimal("1.60"), Decimal("0.64"), Decimal("6.40")),
    ModelPrice("glm-5.3", Decimal("0.60"), Decimal("0.18"), Decimal("2.20")),
    ModelPrice("deepseek-v4-pro", Decimal("0.55"), Decimal("0.14"), Decimal("2.20")),
    ModelPrice("stub", Decimal("0"), Decimal("0"), Decimal("0")),
)
FALLBACK_PRICE = ModelPrice("unknown", Decimal("1.00"), Decimal("0.50"), Decimal("3.00"))


# ---------------------------------------------------------------------------
# Tools and sandbox
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Where tools are allowed to act."""

    root: Path = field(default_factory=Path.cwd)
    allow_execute: bool = True
    execute_timeout_seconds: float = 60.0
    denied_directories: tuple[str, ...] = (".git", ".venv", "node_modules", "__pycache__")

    def __post_init__(self) -> None:
        if self.execute_timeout_seconds <= 0:
            msg = f"execute_timeout_seconds must be positive, got {self.execute_timeout_seconds}"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TuiConfig:
    """Layout of the terminal interface."""

    sidebar_width: int = 34
    show_sidebar: bool = True
    max_rendered_messages: int = 400
    stream_deltas: bool = True

    def __post_init__(self) -> None:
        if self.sidebar_width < 20:
            msg = f"sidebar_width must be at least 20, got {self.sidebar_width}"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


DEFAULT_JUDGE_PROMPT = Path("evals/prompts/judge_v1.md")
"""Versioned judge prompt; a revision is judge_v2.md, never an edit of v1."""

DEFAULT_PROBE_TOOL_CALL_CAP = 3
"""Tool calls the agent may make during one probe round before it must answer."""

DEFAULT_JUDGE_MIN_AGREEMENT = 0.90
"""Calibration gate: hand-labelled agreement the judge must reach before a full run."""


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Shape of the experiment reported in Chapter 4."""

    dataset_dir: Path = field(default_factory=lambda: Path("evals/datasets/long_histories"))
    reports_dir: Path = field(default_factory=lambda: Path(".reports/evals"))
    repetitions: int = 3
    max_cases: int = 5
    judge: Literal["alias", "model"] = "alias"
    upload_to_langsmith: bool = False
    seed: int = 20261031
    probe_tool_call_cap: int = DEFAULT_PROBE_TOOL_CALL_CAP
    judge_prompt_path: Path = DEFAULT_JUDGE_PROMPT
    judge_min_agreement: float = DEFAULT_JUDGE_MIN_AGREEMENT

    def __post_init__(self) -> None:
        if self.repetitions < 1:
            msg = f"repetitions must be at least 1, got {self.repetitions}"
            raise ValueError(msg)
        if self.max_cases < 1:
            msg = f"max_cases must be at least 1, got {self.max_cases}"
            raise ValueError(msg)
        if self.probe_tool_call_cap < 0:
            msg = f"probe_tool_call_cap must be non-negative, got {self.probe_tool_call_cap}"
            raise ValueError(msg)
        if not 0.0 <= self.judge_min_agreement <= 1.0:
            msg = f"judge_min_agreement must be within [0, 1], got {self.judge_min_agreement}"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Root configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the composition root needs, in one immutable object."""

    tokens: TokenAccountingConfig = field(default_factory=TokenAccountingConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    sliding_window: SlidingWindowConfig = field(default_factory=SlidingWindowConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    tool_output: ToolOutputConfig = field(default_factory=ToolOutputConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    endpoints: EndpointConfig = field(default_factory=EndpointConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    tui: TuiConfig = field(default_factory=TuiConfig)
    evaluation: EvalConfig = field(default_factory=EvalConfig)
    agent_name: str = "caio-code"
    system_prompt_file: Path | None = None


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().strip('"').strip("'")


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"{name} must be an integer, got {raw!r}"
        raise ValueError(msg) from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_endpoints(env_file: Path | None = None) -> EndpointConfig:
    """Read credentials from the environment, optionally loading a dotenv file.

    Kept separate from :func:`load_settings` so tests can build settings without
    touching the developer's real keys.
    """
    if env_file is not None:
        try:
            from dotenv import load_dotenv
        except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
            msg = "python-dotenv is required to load a .env file"
            raise RuntimeError(msg) from None
        load_dotenv(env_file, override=False)
    elif Path(".env").is_file():
        try:
            from dotenv import load_dotenv
        except ImportError:  # pragma: no cover
            load_dotenv = None  # type: ignore[assignment]
        if load_dotenv is not None:
            load_dotenv(override=False)

    return EndpointConfig(
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL"),
        typesafe_api_key=_env("TYPESAFE_API_KEY"),
        typesafe_base_url=_env("TYPESAFE_BASE_URL") or DEFAULT_TYPESAFE_BASE_URL,
        langsmith_api_key=_env("LANGSMITH_API_KEY"),
        langsmith_project=_env("LANGSMITH_PROJECT", "caio-code"),
    )


def _decision_provider() -> str:
    """The decision-model provider, defaulting to typesafe when a key is present."""
    explicit = _env("CAIO_CODE_DECISION_PROVIDER")
    if explicit:
        if explicit not in {"stub", "typesafe"}:
            msg = f"unknown decision provider {explicit!r}; expected 'stub' or 'typesafe'"
            raise ValueError(msg)
        return explicit
    return "typesafe" if _env("TYPESAFE_API_KEY") else "stub"


_DECISION_DEFAULTS = DecisionConfig()
"""Single source for the decision defaults; the env wiring below never repeats a literal."""


def _float_env(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        msg = f"{name} must be a number, got {raw!r}"
        raise ValueError(msg) from exc


def _decision_config(endpoints: EndpointConfig) -> DecisionConfig:
    """Decision-model settings from the environment, validated by the dataclass."""
    provider = _decision_provider()
    return DecisionConfig(
        provider=provider,  # type: ignore[arg-type]
        model=_env("CAIO_CODE_DECISION_MODEL") or _DECISION_DEFAULTS.model,
        base_url=(
            _env("CAIO_CODE_DECISION_BASE_URL")
            or endpoints.typesafe_base_url
            or _DECISION_DEFAULTS.base_url
        ),
        timeout_seconds=_float_env(
            "CAIO_CODE_DECISION_TIMEOUT_SECONDS", _DECISION_DEFAULTS.timeout_seconds
        ),
        state_message_char_cap=_int_env(
            "CAIO_CODE_DECISION_STATE_CHAR_CAP", _DECISION_DEFAULTS.state_message_char_cap
        ),
        questions_per_request=_int_env(
            "CAIO_CODE_DECISION_QUESTIONS_PER_REQUEST", _DECISION_DEFAULTS.questions_per_request
        ),
        relevance_threshold=_float_env(
            "CAIO_CODE_DECISION_RELEVANCE_THRESHOLD", _DECISION_DEFAULTS.relevance_threshold
        ),
        risk_threshold=_float_env(
            "CAIO_CODE_DECISION_RISK_THRESHOLD", _DECISION_DEFAULTS.risk_threshold
        ),
    )


def load_settings(
    *,
    env_file: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    window_tokens: int | None = None,
    root: Path | None = None,
) -> Settings:
    """Composition root: environment plus explicit overrides, validated once."""
    endpoints = load_endpoints(env_file)

    resolved_provider = provider or _env("CAIO_CODE_PROVIDER", "stub")
    if resolved_provider == "typesafe":
        msg = (
            "provider 'typesafe' is not a chat provider: Jev is a decision model. "
            "Set CAIO_CODE_DECISION_PROVIDER=typesafe and keep CAIO_CODE_PROVIDER on "
            "stub or openai_compatible"
        )
        raise ValueError(msg)
    if resolved_provider not in {"stub", "openai_compatible"}:
        msg = f"unknown provider {resolved_provider!r}"
        raise ValueError(msg)

    aux_provider = _env("CAIO_CODE_AUX_PROVIDER", resolved_provider)
    if aux_provider == "typesafe":
        msg = "aux_provider 'typesafe' is not a chat provider; see CAIO_CODE_DECISION_PROVIDER"
        raise ValueError(msg)
    if aux_provider not in {"stub", "openai_compatible"}:
        msg = f"unknown aux provider {aux_provider!r}"
        raise ValueError(msg)

    provider_config = ProviderConfig(
        provider=resolved_provider,  # type: ignore[arg-type]
        model=model or _env("CAIO_CODE_MODEL", DEFAULT_AGENT_MODEL),
        aux_provider=aux_provider,  # type: ignore[arg-type]
        aux_model=_env("CAIO_CODE_AUX_MODEL", DEFAULT_AUX_MODEL),
        temperature=float(_env("CAIO_CODE_TEMPERATURE", "0.0") or 0.0),
        max_output_tokens=_int_env("CAIO_CODE_MAX_OUTPUT_TOKENS", 4_096),
        timeout_seconds=float(_env("CAIO_CODE_TIMEOUT_SECONDS", "120") or 120.0),
        aux_timeout_seconds=float(_env("CAIO_CODE_AUX_TIMEOUT_SECONDS", "300") or 300.0),
        max_retries=_int_env("CAIO_CODE_MAX_RETRIES", 2),
    )

    window = WindowConfig(
        tokens=window_tokens or _int_env("CAIO_CODE_WINDOW_TOKENS", 8_000),
        context_limit=_int_env("CAIO_CODE_CONTEXT_LIMIT", 128_000),
        reserved_output_tokens=provider_config.max_output_tokens,
        buffer_tokens=_int_env("CAIO_CODE_WINDOW_BUFFER", 20_000),
    )

    sandbox_root = Path(root or _env("CAIO_CODE_ROOT") or Path.cwd()).expanduser()
    system_prompt = _env("CAIO_CODE_SYSTEM_PROMPT")

    return Settings(
        tokens=TokenAccountingConfig(
            counter=_env("CAIO_CODE_TOKEN_COUNTER", "char_proxy"),  # type: ignore[arg-type]
        ),
        window=window,
        baseline=BaselineConfig(enforce_window=_bool_env("CAIO_CODE_ENFORCE_WINDOW", False)),
        compaction=CompactionConfig(
            keep_tokens=_int_env("CAIO_CODE_COMPACTION_KEEP_TOKENS", 8_000),
            summary_max_tokens=_int_env("CAIO_CODE_SUMMARY_MAX_TOKENS", 4_096),
            tool_result_char_cap=_int_env("CAIO_CODE_TOOL_RESULT_CHAR_CAP", 2_000),
            head_char_cap=_int_env("CAIO_CODE_COMPACTION_HEAD_CHAR_CAP", 100_000),
            summarizer_model=_env("CAIO_CODE_SUMMARIZER_MODEL") or None,
            auto=_bool_env("CAIO_CODE_AUTO_COMPACT", True),
        ),
        tool_output=ToolOutputConfig(
            max_lines=_int_env("CAIO_CODE_TOOL_MAX_LINES", 2_000),
            max_bytes=_int_env("CAIO_CODE_TOOL_MAX_BYTES", 51_200),
        ),
        provider=provider_config,
        endpoints=endpoints,
        decision=_decision_config(endpoints),
        sandbox=SandboxConfig(
            root=sandbox_root.resolve(),
            allow_execute=_bool_env("CAIO_CODE_ALLOW_EXECUTE", True),
        ),
        evaluation=EvalConfig(
            dataset_dir=Path(_env("CAIO_CODE_EVAL_DATASET", "evals/datasets/long_histories")),
            reports_dir=Path(_env("CAIO_CODE_EVAL_REPORTS", ".reports/evals")),
            repetitions=_int_env("CAIO_CODE_EVAL_REPETITIONS", 3),
            max_cases=_int_env("CAIO_CODE_EVAL_MAX_CASES", 5),
            upload_to_langsmith=_bool_env("CAIO_CODE_LANGSMITH_UPLOAD", False),
            probe_tool_call_cap=_int_env(
                "CAIO_CODE_PROBE_TOOL_CALL_CAP", DEFAULT_PROBE_TOOL_CALL_CAP
            ),
            judge_prompt_path=Path(
                _env("CAIO_CODE_JUDGE_PROMPT") or str(DEFAULT_JUDGE_PROMPT)
            ),
            judge_min_agreement=_float_env(
                "CAIO_CODE_JUDGE_MIN_AGREEMENT", DEFAULT_JUDGE_MIN_AGREEMENT
            ),
        ),
        system_prompt_file=Path(system_prompt) if system_prompt else None,
    )
