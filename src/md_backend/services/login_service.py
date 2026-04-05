from md_backend.utils.settings import settings

class LoginService:
    
    async def login(self, email: str, password: str) -> dict:

        if email == settings.ADMIN_EMAIL and password == settings.ADMIN_PASSWORD:
            return {"detail": "Login successful"}
        
        return None