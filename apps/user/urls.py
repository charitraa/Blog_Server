from django.urls import path
from .views import UserPhotoUpdateView , UserUpdateView, LoginView, CreateUserView, UserDetailView
urlpatterns = [
    path('create/', CreateUserView.as_view(), name='user-create'),
    path('photo/', UserPhotoUpdateView.as_view(), name='user-photo-update'),
    path('profile/update/', UserUpdateView.as_view(), name='user-update'),
    path('login/', LoginView.as_view(), name='user-login'),
    path('details/', UserDetailView.as_view(), name='user-detail'),
    # path('github/', GithubOauthSignInView.as_view(), name='github')

]
