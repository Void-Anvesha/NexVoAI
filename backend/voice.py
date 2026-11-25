"""Pipecat WebRTC voice agent. Run with: python -m backend.voice -t webrtc --port 7860"""
import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker, PipelineParams, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.workers.runner import WorkerRunner
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy, TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy
from backend import store
from backend.speech import spoken_times_and_dates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SYSTEM = """You are Careline, a warm, concise clinic appointment assistant. Speak and respond in English. You can check availability, book or cancel. Ask which doctor/specialty and date they prefer. For any booking or cancellation, first ask for the caller's phone number, repeat it digit by digit, and obtain explicit spoken confirmation before using a mutation tool. Never infer caller ID or claim an action succeeded unless the tool confirms it. Offer available choices, use ISO dates and 24h times in tool arguments, and speak naturally. Identity: the caller is identified by phone number plus patient name, because one number can be shared by a family. For a booking, the order is: 1) ask for the phone number and read it back digit by digit for confirmation; 2) then ask for the patient's full name and repeat it back; 3) summarise name, doctor, date and time in one sentence and get a yes; 4) only then call book_appointment with the name. For a cancellation: confirm the phone number, ask whose appointment it is (the patient's name), then call cancel_appointment. After a successful booking, tell the caller the doctor, date and time and say the appointment is confirmed.

Conversation style: this is a phone call. Keep each reply to one or two short sentences and ask one question at a time. Let the caller finish before you respond; if what they said sounds cut off or incomplete (for example a phone number with fewer than ten digits), ask them to continue instead of guessing. Never use lists, bullet points, emojis or markdown, because everything you write is spoken aloud. When offering slots, mention at most three options. When you speak a time or date, say it naturally ("eleven AM", "Thursday the twenty-sixth"), but always pass YYYY-MM-DD and 24-hour HH:MM in tool arguments. Whenever you call a tool, first say a very short holding phrase in the same response, such as "One moment, let me check." or "Booking that for you now.", so the caller never hears silence while you wait for the result."""


GREETING = "Hello, thank you for calling Careline. How can I help you today?"


def system_prompt() -> str:
    # The LLM has no clock; without this it guesses the year (e.g. 2020) and
    # every availability lookup comes back empty.
    today = date.today()
    store.initialize()
    with store.connect() as db:
        first, last = db.execute("SELECT MIN(day), MAX(day) FROM slots WHERE booked=0").fetchone()
    return (
        f"{SYSTEM}\n\nToday is {today:%A, %d %B %Y} ({today.isoformat()}). "
        f"Open slots exist from {first} to {last}. "
        "Resolve relative dates like 'tomorrow' or 'Friday' against today's date."
    )

async def check_doctor_availability(params: FunctionCallParams):
    args = params.arguments
    # Compact, grouped result: a short tool result is read faster by the LLM
    # and an empty day falls back to the next open days in the same call.
    await params.result_callback(store.availability_for_agent(args.get("doctor", ""), args.get("day", "")))

async def book_appointment(params: FunctionCallParams):
    args = params.arguments
    result = store.book(args.get("doctor", ""), args.get("day", ""), args.get("time", ""), args.get("phone", ""), args.get("patient_name", ""))
    await params.result_callback(result)

async def cancel_appointment(params: FunctionCallParams):
    args = params.arguments
    result = store.cancel(args.get("phone", ""), args.get("patient_name", ""), args.get("appointment_id", ""))
    await params.result_callback(result)

TOOLS = ToolsSchema(standard_tools=[
    FunctionSchema(name="check_doctor_availability", description="Find open appointment slots for a doctor or specialty, optionally on a date. Clinic specialties: Cardiology (Dr. Maya Shah), Dermatology (Dr. Aarav Mehta), General medicine (Dr. Leena Iyer), Orthopedics (Dr. Kabir Rao).", properties={"doctor": {"type": "string", "description": "Doctor name or specialty, e.g. 'Dermatology' or 'Dr. Mehta'; empty to search all."}, "day": {"type": "string", "description": "Optional date in YYYY-MM-DD format."}}, required=[]),
    FunctionSchema(name="book_appointment", description="Book an available slot after the caller has confirmed their phone number, the patient's name, and the doctor, date and time.", properties={"doctor": {"type": "string"}, "day": {"type": "string", "description": "Date in YYYY-MM-DD format."}, "time": {"type": "string", "description": "Time in 24-hour HH:MM format."}, "phone": {"type": "string", "description": "The caller's verbally provided, confirmed phone number (digits only)."}, "patient_name": {"type": "string", "description": "Full name of the patient the appointment is for."}}, required=["doctor", "day", "time", "phone", "patient_name"]),
    FunctionSchema(name="cancel_appointment", description="Cancel an active appointment found by the caller's confirmed phone number. The patient name picks the right appointment when several share a number; if the result lists several appointments, ask which one and call again with its appointment_id.", properties={"phone": {"type": "string", "description": "The caller's verbally provided, confirmed phone number (digits only)."}, "patient_name": {"type": "string", "description": "Name of the patient whose appointment should be cancelled."}, "appointment_id": {"type": "string", "description": "Optional appointment id, only when choosing between several."}}, required=["phone", "patient_name"]),
])

async def bot(runner_args: RunnerArguments):
    missing = [name for name in ("ELEVENLABS_API_KEY", "GOOGLE_API_KEY") if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Add them to {PROJECT_ROOT / '.env'} and restart the voice server."
        )
    transport = await create_transport(runner_args, {
        "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    })
    # The realtime model otherwise guesses the language from short greetings;
    # e.g. an English "hi" can be emitted as Japanese "はい". Pin this clinic
    # demo to English so short utterances are transcribed consistently.
    stt = ElevenLabsRealtimeSTTService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsRealtimeSTTService.Settings(
            model="scribe_v2_realtime", language="en"
        ),
    )
    # gemini-3.8/3.7-flash were returning 503 "high demand" on the free tier;
    # 3.6/3.5-flash free tier is only 20 requests/day; flash-lite has its own
    # quota and lower latency. Override with GOOGLE_MODEL.
    llm = GoogleLLMService(
        api_key=os.environ["GOOGLE_API_KEY"],
        settings=GoogleLLMService.Settings(model=os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite"), system_instruction=system_prompt(),
            # Lowest reasoning effort: this is a short-turn phone agent, and
            # thinking tokens are pure latency before the first spoken word.
            thinking=GoogleLLMService.ThinkingConfig(thinking_level="minimal"),
        ),
        # The free tier occasionally stalls a request for 20-80s while the next
        # one answers in ~1s. If no text arrives within 3s, re-issue it once.
        retry_on_timeout=True,
        retry_timeout_secs=3.0,
        # Pipecat's default waits 20s for a stalled retry or a stall mid-reply,
        # which is what made some answers take 20-30s. Give up after 6s instead
        # and recover (see on_completion_timeout below).
        stream_idle_timeout_secs=6.0,
    )
    llm.register_function("check_doctor_availability", check_doctor_availability)
    llm.register_function("book_appointment", book_appointment)
    llm.register_function("cancel_appointment", cancel_appointment)
    tts = ElevenLabsTTSService(api_key=os.environ["ELEVENLABS_API_KEY"], settings=ElevenLabsTTSService.Settings(voice=os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"), model="eleven_flash_v2_5"),
        # Speak "11:00" as "eleven AM" and "2026-11-26" as "Thursday, November twenty-sixth".
        text_transforms=[("*", spoken_times_and_dates)],
    )
    # Gemini expects a conversation to open with a user turn; this marker sits
    # before the spoken greeting so the history alternates user/assistant.
    context = LLMContext(
        messages=[{"role": "user", "content": "(The caller has just connected. You have greeted them.)"}],
        tools=TOOLS,
    )
    # Do not ask the LLM to recover an empty turn. That recovery speaks a
    # "can't hear you" prompt into the microphone, where it can be picked up
    # as fresh user speech and start an echo loop on speakerphone.
    #
    # Turn-taking:
    # - start: while Careline is talking, only 3+ transcribed words count as an
    #   interruption, so echo, breaths or "mm-hm" no longer cut it off
    #   mid-sentence. When it is silent, one word ("yes") starts a turn.
    # - stop: the caller's turn ends when the Smart Turn model judges the
    #   utterance complete AND there has been 0.5s of silence. If the model
    #   thinks the caller isn't done (e.g. mid phone number) it waits, but never
    #   more than 1.5s of silence (library default is 3s), so the caller is
    #   never left in dead air.
    # - mute: the caller can't interrupt the opening greeting.
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            empty_user_turn=None,
            user_turn_strategies=UserTurnStrategies(
                start=[MinWordsUserTurnStartStrategy(min_words=3)],
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=1.5))
                    ),
                    SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.5),
                ],
            ),
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )
    pipeline = Pipeline([transport.input(), stt, user_agg, llm, tts, transport.output(), assistant_agg])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True), idle_timeout_secs=runner_args.pipeline_idle_timeout_secs, processor_unusable_policy=ProcessorUnusablePolicy.END)
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    # When Gemini stalls past the timeouts, don't leave the caller in silence:
    # acknowledge and ask again (twice at most), then ask the caller to repeat.
    llm_timeouts = {"count": 0}

    @llm.event_handler("on_completion_timeout")
    async def on_llm_timeout(service):
        llm_timeouts["count"] += 1
        if llm_timeouts["count"] <= 2:
            await worker.queue_frames([TTSSpeakFrame("Sorry, just a moment.", append_to_context=False), LLMRunFrame()])
        else:
            llm_timeouts["count"] = 0
            await worker.queue_frames([TTSSpeakFrame("Sorry, I'm having trouble on my side. Could you say that again?")])

    @user_agg.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message):
        llm_timeouts["count"] = 0
    @transport.event_handler("on_client_connected")
    async def connected(transport, client):
        # Speak a fixed greeting straight to TTS instead of asking the LLM for
        # one: the free-tier LLM took ~10s to produce it, while this starts in
        # ~0.5s. TTSSpeakFrame also appends the greeting to the LLM context, so
        # Gemini knows it has already greeted the caller.
        await worker.queue_frames([TTSSpeakFrame(GREETING)])
    @transport.event_handler("on_client_disconnected")
    async def disconnected(transport, client):
        await runner.cancel()
    await runner.run()

if __name__ == "__main__":
    from pipecat.runner.run import app, main
    from backend.main import router as dashboard_api

    # Serve the dashboard's /api/doctors, /api/appointments, ... from this same
    # server, so one process runs both the voice agent and the dashboard data.
    store.initialize()
    app.include_router(dashboard_api)
    main()
