# Rules.md — Normas Básicas del Proyecto y de Trabajo

Este documento define los estándares arquitectónicos, operacionales, de jugabilidad y de contribución para el desarrollo del ecosistema **Snake — The Colosseum & SaperaAI (v2.0 Ultimate)**.

---

## 1. Principios de Arquitectura y Código

1. **Principio Abierto/Cerrado (OCP - Open/Closed Principle)**:
   - El núcleo del motor de juego ([`ColosseumRules`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L320)) no se altera para cada nueva dinámica externa.
   - Los eventos de TikTok entran por [`UDPReceiver`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L1085) en el puerto `8765` en formato JSON, se encolan en el [`EventBus`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L254) y se despachan en [`ActionSystem`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L264).

2. **Desacoplamiento Estricto de Responsabilidades**:
   - **Estado ([`ColosseumState`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L235))**: Datos puros sin lógica gráfica.
   - **Reglas Físicas ([`ColosseumRules`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L320))**: Movimiento, alimentación, colisiones justas y control de expiración de eventos.
   - **Inteligencia Artificial ([`MultiAgentBotController`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L650))**: Evaluación multi-agente con anti-colisión frontal, consciencia de tiempo en eventos y escape seguro hacia la cola.
   - **Renderizado ([`ColosseumRenderer`](file:///c:/Users/JSCC2/OneDrive/Documentos/PROYECTOS/SNAKE/2.0.py#L790))**: Interfaz modular, cuenta regresiva animada, modal de pausa y cinemática 3D de la bomba atómica.

---

## 2. Los 4 Modos Oficiales de Juego

1. **⚔️ Battle Royale (4 Serpientes)**:
   - Cuadrícula $22 \times 22$ celdas con las 4 Facciones: `#Rojo` (Kamikaze), `#Verde` (Conservadora), `#Azul` (Territorial) y `#Morado` (Caótica).
   - 4 frutas simultáneas en disputa.
   - La última serpiente en pie gana la ronda, sumando victorias en el marcador global.
2. **🔥 Duelo 1v1 (2 Serpientes)**:
   - Duelo cara a cara entre Fénix Carmesí y Cobra Esmeralda en cuadrícula ampliada.
   - 2 frutas simultáneas.
3. **🌀 Modo Hipnótico (1 Serpiente)**:
   - Espectáculo de streaming clásico: crece con agilidad al inicio, dibuja patrones geométricos fluidos en la fase media y aplica las normas de escape rigurosas en el juego tardío.
4. **⚡ Modo Rápido / Speedrun (1 Serpiente)**:
   - IA voraz de mínima distancia para maximizar la puntuación en el menor tiempo posible sin suicidio.

---

## 3. Normas de Combate, Supervivencia y Fixes de Juego

1. **Cuenta Regresiva de Inicio (3 Segundos)**:
   - Cada ronda inicia congelada con una animación de 3 segundos (3 $\rightarrow$ 2 $\rightarrow$ 1 $\rightarrow$ ¡START!) antes de liberar los movimientos de las serpientes.
2. **Norma Anti-Choque Frontal Prematuro**:
   - Para maximizar la duración del espectáculo, los bots aplican una penalización severa a cualquier casilla a distancia $\le 2$ de una cabeza rival.
   - La agresividad y los rasgos de personalidad se intensifican progresivamente a medida que la serpiente gana longitud.
3. **Reglas del Modo Trascendente (Sin Paredes / Wrap)**:
   - **Consciencia Temporal**: Cuando el modo Trascendente tiene tiempo límite (`wrap_mode_until_ms`), los bots consideran las paredes como **sólidas e impenetrables** si faltan menos de 1.4 segundos para su expiración, impidiendo que la serpiente quede atrapada en el borde al cerrarse el portal.
   - **Preservación Post-Expiración**: Cuando el modo finaliza, los segmentos que ya estaban cruzando el borde no mueren espontáneamente; se les permite completar su tránsito hacia el tablero.
4. **Despojos de Guerra**:
   - Al morir una serpiente, un tercio de sus segmentos se transforma en manzanas de energía que las supervivientes pueden consumir.

---

## 4. Estándar de Menús y Pausa

1. **Menú Principal**:
   - Selección de Modos con preview explicativo.
   - Panel de Controles de Teclado.
   - Guía de Interacciones de TikTok Live.
   - Crédito de autoría: **SaperaAI**.
2. **Menú de Pausa (Tecla `K` o `ESC`)**:
   - Modal deslizable sobre fondo oscuro con opciones de **Reanudar**, **Reiniciar** y **Menú Principal**.

---

## 5. Integración con TikTok Live (`tk.py`)

- **Puerto Unificado**: `8765` UDP.
- **Regalos**:
  - `ROSE`: Bombas estándar temporales.
  - `TIKTOK`: Frutas extra.
  - `GG`: Ciclo de color.
  - `CORAZÓN / DOUGHNUT`: Modo Éxtasis ($2\times$ velocidad y arcoíris).
  - `CORONA / DRAGÓN`: Modo Dorado ($3\times$ velocidad e invulnerabilidad a explosivos).
  - `LEÓN / GALAXY / UNIVERSO`: Bomba Nuclear en perspectiva 3D.
  - `FUEGOS ARTIFICIALES`: Reinicio de ronda.
