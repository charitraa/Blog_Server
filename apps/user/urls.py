from django.urls import path
from .views import UserPhotoUpdateView , UserUpdateView, LoginView, CreateUserView, UserAllDetailView, UserMeView, VerifyEmailView
urlpatterns = [
    path('create/', CreateUserView.as_view(), name='user-create'),
    path('photo/', UserPhotoUpdateView.as_view(), name='user-photo-update'),
    path('profile/update/', UserUpdateView.as_view(), name='user-update'),
    path('login/', LoginView.as_view(), name='user-login'),
    path('details/', UserAllDetailView.as_view(), name='user-detail'),
    path('me/', UserMeView.as_view(), name='user-me'),
    path('verify/', VerifyEmailView.as_view(), name='user-verify'),


    # path('github/', GithubOauthSignInView.as_view(), name='github')

]
