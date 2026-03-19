def remove_cookie_auth(result, generator, request, public):
    """Remove cookieAuth (SessionAuthentication) from the OpenAPI schema.
    Session auth works automatically via browser cookies and does not need
    to appear in the Swagger UI 'Available Authorizations' dialog.
    """
    schemes = result.get('components', {}).get('securitySchemes', {})
    schemes.pop('cookieAuth', None)

    for path in result.get('paths', {}).values():
        for operation in path.values():
            if isinstance(operation, dict) and 'security' in operation:
                operation['security'] = [
                    s for s in operation['security'] if 'cookieAuth' not in s
                ]

    return result
