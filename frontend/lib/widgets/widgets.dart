import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';

class TolLogo extends StatelessWidget {
  final double size;
  final bool whiteBackground;

  const TolLogo({super.key, this.size = 108, this.whiteBackground = false});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        painter: _TolLogoPainter(whiteBackground: whiteBackground),
      ),
    );
  }
}

class _TolLogoPainter extends CustomPainter {
  final bool whiteBackground;

  const _TolLogoPainter({required this.whiteBackground});

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.shortestSide / 108;
    canvas.scale(scale, scale);
    if (whiteBackground) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          const Rect.fromLTWH(0, 0, 108, 108),
          const Radius.circular(24),
        ),
        Paint()..color = Colors.white,
      );
    }

    final orange = Paint()
      ..color = const Color(0xFFFF8A00)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 14
      ..strokeCap = StrokeCap.round;
    final green = Paint()
      ..color = const Color(0xFF0BAA45)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 11
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
        const Rect.fromLTWH(22, 18, 68, 68), -2.78, 2.28, false, orange);
    canvas.drawArc(
        const Rect.fromLTWH(18, 22, 68, 68), 0.36, 2.28, false, orange);
    canvas.drawArc(
        const Rect.fromLTWH(35, 34, 42, 42), -2.76, 2.15, false, green);
    canvas.drawArc(
        const Rect.fromLTWH(31, 32, 42, 42), 0.4, 2.15, false, green);

    final orangeArrow = Paint()..color = const Color(0xFFFF8A00);
    final greenArrow = Paint()..color = const Color(0xFF0BAA45);
    canvas.drawPath(
      Path()
        ..moveTo(14, 30)
        ..lineTo(32, 13)
        ..lineTo(34, 26)
        ..lineTo(48, 29)
        ..lineTo(31, 45)
        ..lineTo(29, 36)
        ..close(),
      orangeArrow,
    );
    canvas.drawPath(
      Path()
        ..moveTo(94, 78)
        ..lineTo(76, 95)
        ..lineTo(74, 82)
        ..lineTo(60, 79)
        ..lineTo(77, 63)
        ..lineTo(79, 72)
        ..close(),
      orangeArrow,
    );
    canvas.drawPath(
      Path()
        ..moveTo(28, 44)
        ..lineTo(41, 29)
        ..lineTo(43, 39)
        ..lineTo(55, 42)
        ..lineTo(41, 55)
        ..lineTo(39, 48)
        ..close(),
      greenArrow,
    );
    canvas.drawPath(
      Path()
        ..moveTo(80, 68)
        ..lineTo(67, 83)
        ..lineTo(65, 73)
        ..lineTo(53, 70)
        ..lineTo(67, 57)
        ..lineTo(69, 64)
        ..close(),
      greenArrow,
    );
  }

  @override
  bool shouldRepaint(covariant _TolLogoPainter oldDelegate) =>
      oldDelegate.whiteBackground != whiteBackground;
}

class StepProgressBar extends StatelessWidget {
  final int currentStep;
  const StepProgressBar({super.key, required this.currentStep});

  static const steps = ['Opérateur', 'Service', 'Informations', 'Paiement'];

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, constraints) {
      final itemWidth = constraints.maxWidth / 4;
      return SizedBox(
        height: 76,
        child: Stack(
          children: [
            Positioned(
              left: itemWidth / 2,
              right: itemWidth / 2,
              top: 20,
              child: Container(height: 2.5, color: Colors.white),
            ),
            Row(
              children: List.generate(4, (index) {
                final step = index + 1;
                final done = step < currentStep;
                final active = step == currentStep;
                return SizedBox(
                  width: itemWidth,
                  child: Column(
                    children: [
                      Container(
                        width: 42,
                        height: 42,
                        decoration: BoxDecoration(
                          color: Colors.white,
                          shape: BoxShape.circle,
                          border: Border.all(
                            color:
                                active ? const Color(0xFF25C84A) : Colors.white,
                            width: active ? 3 : 0,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: 0.08),
                              blurRadius: 8,
                              offset: const Offset(0, 3),
                            ),
                          ],
                        ),
                        child: Center(
                          child: done
                              ? const Icon(Icons.check_rounded,
                                  color: AppColors.success, size: 28)
                              : Text(
                                  '$step',
                                  style: GoogleFonts.nunito(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w900,
                                    color: active
                                        ? AppColors.success
                                        : AppColors.textPrimary,
                                  ),
                                ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        steps[index],
                        maxLines: 1,
                        style: GoogleFonts.nunito(
                          fontSize: 13,
                          fontWeight:
                              active ? FontWeight.w900 : FontWeight.w700,
                          color: Colors.white,
                        ),
                      ),
                    ],
                  ),
                );
              }),
            ),
          ],
        ),
      );
    });
  }
}

class GreenHeader extends StatelessWidget {
  final String title;
  final String subtitle;
  final String icon;
  final int step;
  final bool showBack;
  final VoidCallback? onBack;

  const GreenHeader({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.step,
    this.showBack = true,
    this.onBack,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF008642), Color(0xFF00556C)],
        ),
        borderRadius: BorderRadius.only(
          bottomLeft: Radius.circular(28),
          bottomRight: Radius.circular(28),
        ),
      ),
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 16,
        bottom: 16,
        left: 18,
        right: 18,
      ),
      child: Column(
        children: [
          Stack(
            alignment: Alignment.center,
            children: [
              if (showBack)
                Align(
                  alignment: Alignment.centerLeft,
                  child: IconButton(
                    onPressed: onBack ?? () => Navigator.pop(context),
                    icon: const Icon(Icons.arrow_back_rounded,
                        color: Colors.white, size: 30),
                  ),
                ),
              Container(
                width: 62,
                height: 62,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Icon(
                    step == 4 ? Icons.fact_check_outlined : Icons.edit_document,
                    color: AppColors.success,
                    size: 34,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            title,
            textAlign: TextAlign.center,
            style: GoogleFonts.nunito(
              fontSize: 27,
              fontWeight: FontWeight.w900,
              color: Colors.white,
              height: 1.05,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: GoogleFonts.nunito(
              fontSize: 17,
              height: 1.35,
              fontWeight: FontWeight.w700,
              color: Colors.white.withValues(alpha: 0.92),
            ),
          ),
          const SizedBox(height: 22),
          StepProgressBar(currentStep: step),
        ],
      ),
    );
  }
}

class TolButton extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  final Color? color;
  final bool loading;

  const TolButton({
    super.key,
    required this.label,
    required this.onTap,
    this.color,
    this.loading = false,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 60,
      child: ElevatedButton(
        onPressed: loading ? null : onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: color ?? AppColors.primary,
          foregroundColor: Colors.white,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          elevation: 7,
          shadowColor: AppColors.primary.withValues(alpha: 0.24),
        ),
        child: loading
            ? const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(
                    color: Colors.white, strokeWidth: 2.4),
              )
            : Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    label.replaceAll('›', '').trim(),
                    style: GoogleFonts.nunito(
                      fontSize: 19,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                  if (label.contains('›')) ...[
                    const SizedBox(width: 16),
                    const Icon(Icons.chevron_right_rounded,
                        color: Colors.white, size: 30),
                  ],
                ],
              ),
      ),
    );
  }
}

class TolCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets? padding;
  final VoidCallback? onTap;

  const TolCard({super.key, required this.child, this.padding, this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE9ECF4)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.06),
              blurRadius: 16,
              offset: const Offset(0, 5),
            ),
          ],
        ),
        padding: padding ?? const EdgeInsets.all(16),
        child: child,
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  final String title;
  const SectionTitle(this.title, {super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(
        title.toUpperCase(),
        style: GoogleFonts.nunito(
          fontSize: 17,
          fontWeight: FontWeight.w900,
          color: AppColors.textPrimary,
          letterSpacing: 0,
        ),
      ),
    );
  }
}

class StatusBadge extends StatelessWidget {
  final String status;
  const StatusBadge(this.status, {super.key});

  @override
  Widget build(BuildContext context) {
    final isOk = status == 'ok';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: isOk ? AppColors.primaryLight : AppColors.redLight,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        isOk ? 'Réussie' : 'Échouée',
        style: GoogleFonts.nunito(
          fontSize: 11,
          fontWeight: FontWeight.w900,
          color: isOk ? AppColors.primary : AppColors.red,
        ),
      ),
    );
  }
}

class QuickAmountButton extends StatelessWidget {
  final int amount;
  final bool selected;
  final VoidCallback onTap;

  const QuickAmountButton({
    super.key,
    required this.amount,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        decoration: BoxDecoration(
          color: selected ? AppColors.primary : Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? AppColors.primary : const Color(0xFFE7EAF2),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.04),
              blurRadius: 10,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        // Le contenu reste compact pour ne jamais depasser la cellule de
        // grille sur les petits ecrans.
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              amount == 0 ? 'Autre' : '$amount',
              style: GoogleFonts.nunito(
                fontSize: amount == 0 ? 16 : 17,
                fontWeight: FontWeight.w900,
                color: selected ? Colors.white : AppColors.textPrimary,
              ),
            ),
            Text(
              amount == 0 ? 'montant' : 'FCFA',
              style: GoogleFonts.nunito(
                fontSize: amount == 0 ? 13 : 12,
                fontWeight: FontWeight.w600,
                color: selected ? Colors.white : AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
