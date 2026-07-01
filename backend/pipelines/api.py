from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import ModelSchema, Router
from ninja.security import APIKeyHeader, django_auth
from buoy_retriever.auth import JWTAuthCreateUser

from .models import Pipeline, PipelineApiKey

router = Router()


class PipelineApiKeyAuth(APIKeyHeader):
    """API Key header authentication for pipeline API keys"""

    param_name = "X-API-KEY"

    def authenticate(self, request: HttpRequest, key: str):
        try:
            api_key = PipelineApiKey.objects.get(key_value=key, is_active=True)
            return api_key
        except PipelineApiKey.DoesNotExist:
            return None


pipeline_api_key_auth = PipelineApiKeyAuth()

PIPELINE_DJANGO_OR_JWT_AUTH = (
    pipeline_api_key_auth,
    django_auth,
    JWTAuthCreateUser(),
)


class PipelineSchema(ModelSchema):
    class Meta:
        model = Pipeline
        fields = [
            "id",
            "slug",
            "name",
            "config_schema",
            "description",
            "created",
            "edited",
            "active",
        ]


class PipelinePostSchema(ModelSchema):
    class Meta:
        model = Pipeline
        fields = ["slug", "name", "config_schema", "description"]


@router.get(
    "/",
    response=list[PipelineSchema],
    auth=PIPELINE_DJANGO_OR_JWT_AUTH,
)
def list_pipelines(request: HttpRequest):
    """List all pipelines"""
    return Pipeline.objects.all()


@router.post("/", response=PipelineSchema, auth=pipeline_api_key_auth)
def create_update_pipeline(request: HttpRequest, payload: PipelinePostSchema):
    """If a pipeline with the given slug already exists, update it instead of creating a new one."""
    try:
        existing = Pipeline.objects.get(slug=payload.slug)
        existing.name = payload.name
        existing.config_schema = payload.config_schema
        existing.description = payload.description
        existing.active = True
        existing.save()
        return existing
    except Pipeline.DoesNotExist:
        pipeline = Pipeline(**payload.dict())
        pipeline.save()
        return pipeline


@router.get(
    "/{id}/",
    response=PipelineSchema,
    auth=PIPELINE_DJANGO_OR_JWT_AUTH,
)
def get_pipeline_by_id(request: HttpRequest, id: int):
    """Get a specific pipeline by ID"""
    pipeline = get_object_or_404(Pipeline, id=id)
    return pipeline
