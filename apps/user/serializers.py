from django.contrib.auth import get_user_model
from rest_framework import serializers
import random
import string
from django.contrib.auth.password_validation import validate_password
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
        fields = ['first_name', 'last_name', 'email', 'password', 'confirm_password']

    def random_string(self, length):
        letters = string.ascii_letters + string.digits
        return ''.join(random.choice(letters) for i in range(length))

    def validate(self, attrs):
        # Ensure passwords match
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"message": "Passwords do not match."})

        # Validate password strength using Django’s built-in validators
        validate_password(attrs['password'])

        # Ensure email is unique
        if User.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"message": "A user with this email already exists."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            username=f"{validated_data['first_name']}_{self.random_string(3)}"
        )
        return user
    
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'
        exclude = ['password']

class UserPhotoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['photo']
        
    def validate_photo(self, value):
        # 5 MB limit
        max_size = 5 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError("Photo size should not exceed 5MB.")
        return value

class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'username', 'date_of_birth', 'bio', 'district', 'city']

    def update(self, instance, validated_data):
        # Prevent email duplication
        if 'email' in validated_data:
            new_email = validated_data['email']
            if User.objects.filter(email=new_email).exclude(id=instance.id).exists():
                raise serializers.ValidationError({"email": "This email is already in use."})
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
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
        fields = ['current_password', 'new_password', 'new_password_confirm']

    def validate(self, attrs):
        user = self.instance
        if not user.check_password(attrs['current_password']):
            raise serializers.ValidationError({"message": "Current password is incorrect."})
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({"message": "New passwords do not match."})
        validate_password(attrs['new_password'])
        return attrs

    def update(self, instance, validated_data):
        instance.set_password(validated_data['new_password'])
        instance.save()
        return instance
