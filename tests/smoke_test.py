from playwrite_distiller.distiller import run_accessibility_distillation_sync

result = run_accessibility_distillation_sync("https://google.com")
print(f"Distiller result: {result.suggestion_report}")