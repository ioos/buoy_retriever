import logging

# from django.db.models import Q
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.conf import settings
from django.contrib.auth.models import AbstractUser


logger = logging.getLogger(__name__)

# TODO: Placeholder