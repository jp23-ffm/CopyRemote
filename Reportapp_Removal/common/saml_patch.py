import logging
import saml2.response

logger = logging.getLogger(__name__)

# Guarda la referencia al método original
original_session_info = saml2.response.AuthnResponse.session_info

def patched_session_info(self):
    # Llama al método original para obtener la información de sesión
    info = original_session_info(self)
    # Si en el diccionario resultante 'ava' está vacío o es falsy, inyecta 'uid'
    if not info.get("ava") and self.name_id and hasattr(self.name_id, "text") and self.name_id.text:
        logger.debug("Parche: inyectando 'uid' en AVA con valor '%s' a partir del NameID", self.name_id.text)
        info["ava"] = {"uid": [self.name_id.text]}
    return info

# Reemplaza el método original por el parcheado
saml2.response.AuthnResponse.session_info = patched_session_info
