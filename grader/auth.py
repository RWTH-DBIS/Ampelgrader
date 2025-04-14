from django import http
from django.utils.http import urlencode
from django.conf import settings

def provider_logout(request):
  """ Create the user's OIDC logout URL."""
  oidc_id_token = request.session.get('oidc_id_token', None)
  
  if not oidc_id_token:
    return http.HttpResponse("No OIDC ID token found in session.", status=400)
  else:
    logout_url = (
        settings.OIDC_OP_LOGOUT_ENDPOINT
        + "?"
        + urlencode(
            {
                "id_token_hint": oidc_id_token,
                "post_logout_redirect_uri": request.build_absolute_uri(
                    location=settings.LOGOUT_REDIRECT_URL
                )
            }
        )
    )

  return logout_url

from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import User

class CustomOIDCAuthenticationBackend(OIDCAuthenticationBackend):
    def update_user(self, user, claims):
        """
        Update user given the role from keycloak
        """
        try:
          roles = claims.get("realm_access", {}).get("roles", [])
          client_roles = claims.get("resource_access", {}).get("nbblackbox", {}).get("roles", [])

          print(roles, client_roles)
        except Exception as e:
          print(f"Error getting roles from claims: {e}")
        
        if 'ampel-testgroup' in roles:
            user.is_staff = True
            user.is_superuser = True
        else:
            user.is_staff = False
            user.is_superuser = False
        user.save()

        return user
