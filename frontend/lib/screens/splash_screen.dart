import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import '../services/backend_api_service.dart';
import 'home_screen.dart';

// Ce nom est conservé pour ne pas casser le branchement existant dans
// main.dart. Pour le moment, l'application affiche directement l'accueil.
class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    // On crée les services sans session enregistrée. L'accueil peut donc
    // s'afficher même si le backend ou le stockage sécurisé est indisponible.
    return HomeScreen(
      backendApiService: BackendApiService(),
      authService: AuthService(),
    );
  }
}
