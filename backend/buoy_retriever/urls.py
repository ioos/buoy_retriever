"""
URL configuration for buoy_retriever project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView

from .api import api

prefix = "backend/"

urlpatterns = [
    path(f"{prefix}admin/", admin.site.urls),
    path(f"{prefix}api/", api.urls),
    path(
        f"{prefix}health/",
        HealthCheckView.as_view(
            checks=[
                # "health_check.Cache",
                "health_check.Database",
                # "health_check.Mail",
                # "health_check.Storage",
                # 3rd party checks
                # "health_check.contrib.psutil.Disk",
                # "health_check.contrib.psutil.Memory",
                # "health_check.contrib.celery.Ping",
                # "health_check.contrib.rabbitmq.RabbitMQ",
                # "health_check.contrib.redis.Redis",
            ],
        ),
    ),  # health check endpoints
    path(prefix, include("django.contrib.auth.urls")),
]
