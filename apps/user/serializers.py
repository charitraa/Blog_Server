from django.contrib.auth import get_user_model
from rest_framework import serializers
import random
import string
# from .github import Github
# from .helper import register_social_user

User = get_user_model()

class UserCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration with all required fields.
    """
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, min_length=8, required=True)
    confirm_password = serializers.CharField(write_only=True, min_length=8, required=True)
    class Meta:
        model = User
        fields ='__all__'

    def random_string(self, length):
        letters = string.ascii_letters + string.digits
        return ''.join(random.choice(letters) for i in range(length))

    def create(self, validated_data):
        """
         Create and return a new user with the validated data.
        """
        if User.objects.filter(email=validated_data['email']).exists():
            raise serializers.ValidationError({'message': 'A user with this email already exists.'})
        if validated_data['password'] != validated_data['confirm_password']:
            raise serializers.ValidationError({'message': 'Passwords do not match.'})
        user = User.objects.create_user(
            username=validated_data['first_name'] + '_' + self.random_string(2),
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],)
        return user
    
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'

class UserPhotoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['photo']

class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'username', 'date_of_birth', 'bio', 'district', 'city']
    def update(self, instance, validated_data):
        # Prevent email from being updated to something already in use
        if 'email' in validated_data and User.objects.filter(email=validated_data['email']).exclude(id=instance.id).exists():
            raise serializers.ValidationError({"email": "This email is already in use."})   
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.username = validated_data.get('username', instance.username)
        instance.date_of_birth = validated_data.get('date_of_birth', instance.date_of_birth)
        instance.bio = validated_data.get('bio', instance.bio)
        instance.district = validated_data.get('district', instance.district)
        instance.city = validated_data.get('city', instance.city)
        instance.save()
        return instance

# class GithubLoginSerializer(serializers.Serializer):
#     code = serializers.CharField()

#     def validate_code(self, code):
#         print("Received Code: ", code)  # Debugging the received code
        
#         access_token = Github.exchange_code_for_token(code)
        
#         if not access_token:
#             raise serializers.ValidationError("Invalid code or failed to get access token from GitHub.")
        
#         print("Access Token: ", access_token)  # Debugging the access token
        
#         user_data = Github.get_github_user(access_token)
        
#         if not user_data:
#             raise serializers.ValidationError("Failed to fetch user data from GitHub.")
        
#         # Handle user data (name and email)
#         full_name = user_data.get('name', '')
#         email = user_data.get('email', '')
#         names = full_name.split(" ")
#         first_name = names[0] if len(names) > 0 else ''
#         last_name = names[1] if len(names) > 1 else ''
        
#         provider = 'github'
        
#         # Register or get user
#         return register_social_user(provider, email, first_name, last_name)

class PasswordUpdateSerializer(serializers.ModelSerializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('username', 'phone_number', 'full_name', 'address', 'current_password', 'new_password', 'new_password_confirm')

    def validate(self, attrs):
        user = self.instance
        current_password = attrs.get('current_password')
        new_password = attrs.get('new_password')
        new_password_confirm = attrs.get('new_password_confirm')

        # Check current password is correct
        if not user.check_password(current_password):
            raise serializers.ValidationError({"current_password": "Current password is incorrect."})

        # Check new password confirmation
        if new_password != new_password_confirm:
            raise serializers.ValidationError({"new_password_confirm": "New password fields didn't match."})

        return attrs

    def update(self, instance, validated_data):
        # Update password if provided
        new_password = validated_data.get('new_password')
        if new_password:
            instance.set_password(new_password)

        instance.save()
        return instance