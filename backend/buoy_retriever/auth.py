from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed, InvalidToken
from ninja_jwt.settings import api_settings


# From: https://github.com/eadwinCode/django-ninja-jwt/issues/32
class JWTAuthCreateUser(JWTAuth):
    """Assist with creating a user upon successful JWT validation."""

    def get_user(self, validated_token) -> AbstractUser:
        """
        Attempts to find and return a user using the given validated token.
        """
        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError as e:
            raise InvalidToken(
                _("Token contained no recognizable user identification"),
            ) from e

        try:
            # Create the user if it doesn't exist
            user, created = self.user_model.objects.get_or_create(
                **{api_settings.USER_ID_FIELD: user_id},
            )
        except self.user_model.DoesNotExist as e:
            raise AuthenticationFailed(_("User not found")) from e

        if not user.is_active:
            raise AuthenticationFailed(_("User is inactive"))

        return user
