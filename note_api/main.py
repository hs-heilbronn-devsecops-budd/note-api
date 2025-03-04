# -*- coding: utf-8 -*-
from uuid import uuid4
from typing import List, Optional
from os import getenv, environ
from typing_extensions import Annotated

from fastapi import Depends, FastAPI
from starlette.responses import RedirectResponse
from .backends import Backend, RedisBackend, MemoryBackend, GCSBackend
from .model import Note, CreateNoteRequest

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.resources import SERVICE_NAME

# Set Google Cloud Project ID
# Ensure the environment variable GOOGLE_CLOUD_PROJECT is set
project_id = environ.get("GOOGLE_CLOUD_PROJECT", "hs-heilbronn-devsecops")
if not project_id:
    raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is not set")

# Initialize tracing with proper resource
resource = Resource(attributes={
    SERVICE_NAME: "note-api"
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer("my.tracer")

# Setup the Google Cloud Trace exporter
cloud_trace_exporter = CloudTraceSpanExporter(project_id=project_id)
span_processor = BatchSpanProcessor(cloud_trace_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Initialize FastAPI app
app = FastAPI()

my_backend: Optional[Backend] = None


def get_backend() -> Backend:
    global my_backend  # pylint: disable=global-statement
    if my_backend is None:
        backend_type = getenv('BACKEND', 'memory')
        print(f"Backend type: {backend_type}")
        if backend_type == 'redis':
            my_backend = RedisBackend()
        elif backend_type == 'gcs':
            my_backend = GCSBackend()
        else:
            my_backend = MemoryBackend()
    return my_backend


@app.get('/')
def redirect_to_notes() -> None:
    return RedirectResponse(url='/notes')


@app.get('/notes')
def get_notes(backend: Annotated[Backend, Depends(get_backend)]) -> List[Note]:
    with tracer.start_as_current_span("get_all_notes") as span:
        keys = backend.keys()
        notes = []
        span.set_attribute("note_count", len(keys))
        for key in keys:
            notes.append(backend.get(key))
        return notes


@app.get('/notes/{note_id}')
def get_note(note_id: str, backend: Annotated[Backend, Depends(get_backend)]) -> Note:
    with tracer.start_as_current_span("get_note") as span:
        span.set_attribute("note_id", note_id)
        return backend.get(note_id)


@app.put('/notes/{note_id}')
def update_note(note_id: str, request: CreateNoteRequest, backend: Annotated[Backend, Depends(get_backend)]) -> None:
    with tracer.start_as_current_span("update_note") as span:
        span.set_attribute("note_id", note_id)
        span.set_attribute("title", request.title)
        backend.set(note_id, request)


@app.post('/notes')
def create_note(request: CreateNoteRequest, backend: Annotated[Backend, Depends(get_backend)]) -> str:
    with tracer.start_as_current_span("create_note") as span:
        note_id = str(uuid4())
        span.set_attribute("note_id", note_id)
        span.set_attribute("title", request.title)
        backend.set(note_id, request)
        return note_id


# Instrument the FastAPI application
FastAPIInstrumentor.instrument_app(app)