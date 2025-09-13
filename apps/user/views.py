from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
import random
from django.core.mail import send_mail
from django.utils import timezone
from django.contrib.auth import get_user_model, authenticate
from datetime import timedelta
from apps.user.models import LoginCode
from blog_server import settings
from blog_server.permission import LoginRequiredPermission
from .serializers import UserPhotoUpdateSerializer , UserUpdateSerializer , UserSerializer, UserCreateSerializer

User = get_user_model()


class LoginView(TokenObtainPairView):
    """
    Custom login view that supports authentication via email or username.
    """

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            return Response({"message": "Email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = authenticate(email=email, password=password)

            if user is not None:
                if user.is_verified:
                    refresh = RefreshToken.for_user(user)
                    user_serializer = UserSerializer(user)
                    response = Response({
                        'message': 'Login successful',
                        'data': user_serializer.data,
                        'access': str(refresh.access_token),
                        'refresh': str(refresh),
                    }, status=status.HTTP_200_OK)

                    response.set_cookie(
                    key="access_token",
                    value=str(refresh.access_token),
                    httponly=True,
                    secure=True,  # Must be True in production
                    samesite="None"  # Only use "None" when `secure=True`
                    )
                    return response
                else:
                    code = str(random.randint(100000, 999999))
                    LoginCode.objects.create(
                    user=user,
                    code=code,
                    expires_at=timezone.now() + timedelta(minutes=10)  # valid for 10 min
                    )
                    send_mail(
                    "Your Login Verification Code",
                    f"Hello {user.first_name},\n\nYour verification code is: {code}\n\nIf you did not try to login, please ignore this email.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                    )
                    return Response({"message": "Verification code sent to your email."}, status=status.HTTP_200_OK)


        except User.DoesNotExist:
            return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

class VerifyEmailView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        code = request.data.get("code")

        try:
            user = User.objects.get(email=email)
            verification = LoginCode.objects.filter(user=user, code=code).last()

            if not verification:
                return Response({"message": "Invalid code"}, status=status.HTTP_400_BAD_REQUEST)

            if verification.is_expired():
                return Response({"message": "Code expired"}, status=status.HTTP_400_BAD_REQUEST)

            # ✅ Mark user as verified
            user.is_verified = True
            user.save()
            refresh = RefreshToken.for_user(user)
            user_serializer = UserSerializer(user)
            response = Response({
                'message': 'Email verified and login successful',
                'data': user_serializer.data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }, status=status.HTTP_200_OK)

            response.set_cookie(
                key="access_token",
                value=str(refresh.access_token),
                httponly=True,
                secure=True,  # Must be True in production
                samesite="None"  # Only use "None" when `secure=True`
            )
            return response
        
        except User.DoesNotExist:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

class UserAllDetailView(APIView):
    permission_classes = [LoginRequiredPermission]
    def get(self, request, *args, **kwargs):
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)

class UserMeView(APIView):
    permission_classes = [LoginRequiredPermission]
    def get(self, request, *args, **kwargs):
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data)

class UserUpdateView(generics.UpdateAPIView):
    queryset = User.objects.all()  
    serializer_class = UserUpdateSerializer  
    permission_classes = [LoginRequiredPermission]
    def get_object(self):
        return self.request.user
    
class CreateUserView(APIView):
    """
    View for user registration.
    """
    def post(self, request, *args, **kwargs):
        serializer = UserCreateSerializer(data=request.data)
        if serializer.is_valid(is_verified=False, raise_exception=True):
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPhotoUpdateView(generics.UpdateAPIView):
    serializer_class = UserPhotoUpdateSerializer
    permission_classes = [LoginRequiredPermission]

    def get_object(self):
        return self.request.user
    
# class GithubOauthSignInView(GenericAPIView):
#     serializer_class = GithubLoginSerializer

#     def post(self, request):
#         print("Request Data: ", request.data)  # Debugging the request data
        
#         if 'code' not in request.data:
#             return Response({"error": "Code not provided"}, status=status.HTTP_400_BAD_REQUEST)
        
#         serializer = self.serializer_class(data=request.data)
        
#         if serializer.is_valid(raise_exception=True):
#             data = serializer.validated_data
#             return Response({"message": "User authenticated successfully", "user_data": data}, status=status.HTTP_200_OK)
        
#         return Response(serializer.errors, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
