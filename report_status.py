# Snake — The Colosseum & SaperaAI — Reporte en Vivo de las 6 Arenas
import os
import sys
import json
import glob

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def generate_report():
    results_dir = "training_results"
    files = sorted(glob.glob(os.path.join(results_dir, "weights_*.json")))
    if not files:
        print("No se encontraron checkpoints en training_results/")
        return

    print("=" * 75)
    print("  ESTADO EN VIVO DE LAS 6 ARENAS DE SIMULACIÓN PARALELA")
    print("=" * 75)

    total_matches = 0
    total_time = 0

    for f in files:
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        arena_id = data.get("arena_id", os.path.basename(f))
        matches = data.get("matches", 0)
        elapsed = data.get("elapsed_sec", 0)
        wins = data.get("wins", {})
        total_matches += matches
        total_time = max(total_time, elapsed)

        hours = round(elapsed / 3600, 2)
        print(f"\n🏟️ Arena: {arena_id}")
        print(f"   Partidas totales : {matches:,} | Tiempo activo: {hours}h ({elapsed:.0f}s)")
        print(f"   Distribución de Victorias:")
        for fac, cnt in sorted(wins.items(), key=lambda x: -x[1]):
            pct = round((cnt / max(1, matches)) * 100, 1)
            print(f"     - {fac:7s} : {cnt:6,d} victorias ({pct}%)")

    print("\n" + "=" * 75)
    print(f"  RESUMEN GLOBAL: {total_matches:,} partidas disputadas en {round(total_time/3600, 2)}h")
    print("=" * 75)

if __name__ == "__main__":
    generate_report()
