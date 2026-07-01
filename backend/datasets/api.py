from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from guardian.core import ObjectPermissionChecker
from guardian.shortcuts import get_objects_for_user
from ninja import ModelSchema, Router, Schema
from ninja.errors import AuthorizationError
from ninja.security import django_auth
from buoy_retriever.auth import JWTAuthCreateUser

from pipelines.api import pipeline_api_key_auth
from pipelines.models import Pipeline

from .models import Dataset, DatasetConfig

DJANGO_OR_JWT_AUTH = (
    django_auth,
    JWTAuthCreateUser(),
)
PIPELINE_OR_JWT_AUTH = (
    pipeline_api_key_auth,
    JWTAuthCreateUser(),
)

dataset_router = Router(auth=DJANGO_OR_JWT_AUTH)
config_router = Router(auth=DJANGO_OR_JWT_AUTH)


class DatasetCompactSchema(ModelSchema):
    class Meta:
        model = Dataset
        fields = ["slug", "state", "created", "edited"]


class DatasetCompactPermissionsSchema(Schema):
    user_can_edit: bool
    user_can_publish: bool

    slug: str
    state: str
    # created
    # edited

    @staticmethod
    def resolve_user_can_edit(obj: Dataset, context) -> bool:
        user = context["request"].user
        return obj.can_edit(user)

    @staticmethod
    def resolve_user_can_publish(obj: Dataset, context) -> bool:
        user = context["request"].user
        return obj.can_publish(user)


class DatasetWithConfigSchema(Schema):
    slug: str
    config: dict
    config_state: str
    # created: str
    # edited: str


class DatasetCreateSchema(ModelSchema):
    pipeline_id: int

    class Meta:
        model = Dataset
        fields = ["slug"]


class DatasetSchema(ModelSchema):
    configs: list["DatasetConfigCompactSchema"]

    class Meta:
        model = Dataset
        fields = ["id", "slug", "pipeline", "state", "created", "edited"]


class DatasetConfigCompactSchema(ModelSchema):
    class Meta:
        model = DatasetConfig
        fields = ["config", "created", "edited", "state", "id"]


class DatasetConfigSchema(ModelSchema):
    dataset: DatasetCompactSchema

    class Meta:
        model = DatasetConfig
        fields = ["id", "dataset", "config", "state", "created", "edited"]


class DatasetConfigPostSchema(ModelSchema):
    class Meta:
        model = DatasetConfig
        fields = ["config"]


@dataset_router.get("/", response=list[DatasetCompactPermissionsSchema])
def list_datasets(request: HttpRequest):
    """List all datasets"""
    datasets = get_objects_for_user(
        request.user,
        "datasets.view_dataset",
    )
    checker = ObjectPermissionChecker(request.user)
    checker.prefetch_perms(datasets)

    return datasets


@dataset_router.post("/", response=DatasetSchema)
def create_dataset(request: HttpRequest, payload: DatasetCreateSchema):
    """Create a new dataset"""
    pipeline = get_object_or_404(Pipeline, id=payload.pipeline_id)
    user = request.user
    print(f"Creating dataset {payload.slug} for pipeline: {pipeline} by user: {user}")

    data = payload.dict()
    del data["pipeline_id"]

    dataset = Dataset(**data, pipeline=pipeline)
    dataset.save()
    dataset.assign_edit_permission(user)
    config = DatasetConfig(dataset=dataset)
    config.save()
    return dataset


@dataset_router.get("/{slug}/", response=DatasetSchema)
def get_dataset(request: HttpRequest, slug: str):
    """Get a specific dataset by slug"""
    dataset = Dataset.objects.prefetch_related("configs").get(slug=slug)

    if not dataset.can_view(request.user):
        raise AuthorizationError("You do not have permission to view this dataset.")
    return dataset


@dataset_router.get(
    "/by-pipeline/{pipeline_slug}/",
    response=list[DatasetSchema],
    auth=PIPELINE_OR_JWT_AUTH,
)
def get_datasets_by_pipeline(request: HttpRequest, pipeline_slug: str):
    """Get all datasets for a specific pipeline"""
    datasets = Dataset.objects.filter(
        pipeline__slug=pipeline_slug,
        configs__state__in=[DatasetConfig.State.PUBLISHED, DatasetConfig.State.TESTING],
    ).prefetch_related("configs")

    return datasets


@config_router.get("{id}/", response=DatasetConfigSchema)
def get_config(request: HttpRequest, id: int):
    """Get a specific dataset config by ID"""
    config = get_object_or_404(DatasetConfig, id=id)

    if not config.dataset.can_view(request.user):
        raise AuthorizationError(
            "You do not have permission to view this dataset config.",
        )

    return config


@config_router.post("{id}/", response=DatasetConfigSchema)
def post_config(request: HttpRequest, id: int, payload: DatasetConfigPostSchema):
    """Update a specific dataset config by ID"""
    config = get_object_or_404(DatasetConfig, id=id)

    if not config.dataset.can_edit(request.user):
        raise AuthorizationError(
            "You do not have permission to edit this dataset config.",
        )

    for attr, value in payload.dict().items():
        setattr(config, attr, value)
    config.save()
    return config


@config_router.get(
    "by-pipeline/{pipeline_slug}/",
    response=list[DatasetWithConfigSchema],
    auth=PIPELINE_OR_JWT_AUTH,
)
def get_configs_by_pipeline(request: HttpRequest, pipeline_slug: str):
    """Get all active published or testing dataset configs for a specific pipeline"""
    configs = DatasetConfig.objects.filter(
        dataset__pipeline__slug=pipeline_slug,
        state__in=[DatasetConfig.State.PUBLISHED, DatasetConfig.State.TESTING],
        dataset__state=Dataset.State.ACTIVE,
    ).select_related("dataset")

    datasets = []

    for config in configs:
        dataset = DatasetCompactSchema.from_orm(config.dataset)
        dataset_dict = dataset.dict()
        dataset_dict["config"] = config.config
        dataset_dict["config_state"] = config.state

        if config.state == DatasetConfig.State.TESTING:
            dataset_dict["slug"] += "_testing"

        datasets.append(dataset_dict)

    return datasets
