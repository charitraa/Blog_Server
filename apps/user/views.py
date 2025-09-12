from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from .serializers import UserPhotoUpdateSerializer , UserUpdateSerializer , UserSerializer, UserCreateSerializer
from django.contrib.auth import get_user_model, authenticate
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from blog_server.permission import LoginRequiredPermission
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

        except User.DoesNotExist:
            return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)


class UserDetailView(APIView):
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
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPhotoUpdateView(generics.UpdateAPIView):
    serializer_class = UserPhotoUpdateSerializer
    permission_classes = [IsAuthenticated]

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
