"""Microsoft Agent Framework setup — Azure OpenAI agent with tool calling."""

import asyncio
import logging

from agent_framework import Agent
from agent_framework.azure import AzureOpenAIChatClient

from config.settings import Settings
from data.loader import DataLoader
from agent.plugins.data_plugin import create_data_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a data assistant inside Microsoft Teams. Users ask natural-language \
questions about tabular data and you answer with precise facts from the dataset.

Rules:
1. Always call the available data functions — never guess or fabricate data.
2. Report exact counts and full records. Never sample, truncate, or approximate.
3. When get_rows or query_table returns a summary saying data was sent directly \
   to the user, do NOT repeat or fabricate the row data. Simply acknowledge the \
   result (e.g. "Here are the 200 matching rows.") and mention the query/filter used.
4. After presenting data, briefly state what query/filter you used and how many \
   rows matched.
5. If the data cannot answer a question, say so clearly.
"""


class AgentKernel:
    """Wraps the Microsoft Agent Framework with per-conversation sessions."""

    def __init__(self, settings: Settings, data_loader: DataLoader) -> None:
        # Shared buffers for data that bypasses the LLM
        self._data_buffer: list[str] = []
        self._file_buffer: list[dict] = []
        self._buffer_lock = asyncio.Lock()

        # Azure OpenAI chat client
        client = AzureOpenAIChatClient(
            api_key=settings.azure_openai_api_key,
            endpoint=settings.azure_openai_endpoint,
            deployment_name=settings.azure_openai_deployment_name,
        )

        # Data tools (bound to the shared buffers)
        tools = create_data_tools(data_loader, self._data_buffer, self._file_buffer)

        # Build the agent
        self._agent = Agent(
            client=client,
            instructions=SYSTEM_PROMPT,
            tools=tools,
        )

        # Per-conversation sessions (preserves chat history)
        self._sessions: dict[str, object] = {}
        logger.info(
            "AgentKernel initialised (deployment=%s)",
            settings.azure_openai_deployment_name,
        )

    def _get_session(self, conversation_id: str):
        """Return (or create) the AF session for a conversation."""
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = self._agent.create_session()
        return self._sessions[conversation_id]

    async def ask(self, conversation_id: str, user_message: str) -> dict:
        """Send a user message through the agent and return the reply.

        Returns:
            dict with "text" (LLM response), "data_chunks" (list of markdown
            tables), and "files" (list of generated file metadata) — all sent
            directly to the user, bypassing the LLM.
        """
        async with self._buffer_lock:
            self._data_buffer.clear()
            self._file_buffer.clear()
            session = self._get_session(conversation_id)

            try:
                result = await self._agent.run(
                    user_message,
                    session=session,
                    tool_choice="auto",
                )
                response_text = result.text if result else (
                    "I couldn't generate a response. Please try again."
                )
            except Exception as exc:
                logger.error("Agent error: %s", exc, exc_info=True)
                response_text = f"⚠️ Error processing your request: {exc}"

            data_chunks = list(self._data_buffer)
            files = list(self._file_buffer)
            self._data_buffer.clear()
            self._file_buffer.clear()

            return {"text": response_text, "data_chunks": data_chunks, "files": files}
