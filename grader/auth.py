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
