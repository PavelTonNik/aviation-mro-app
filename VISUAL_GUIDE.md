# 🎨 Визуальное руководство по новому дашборду

## 1. Главный экран (Dashboard)

### Было (старый дизайн):
```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   ER-BAT     │  │   ER-BAR     │  │   ER-BAQ     │
│              │  │              │  │              │
│   [Просто    │  │   [Просто    │  │   [Просто    │
│    синяя     │  │    синяя     │  │    синяя     │
│    кнопка]   │  │    кнопка]   │  │    кнопка]   │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Стало (новый дизайн):
```
┌─────────────────────────────────────────────┐
│ ER-BAT                      ✈️              │
│                          45,623.5 hrs       │
│                            28,450 cyc       │
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ │
│                                             │
│ [Position cards - collapsed by default]    │
│                                             │
│ ─────────────────────────────────────────── │
│                   ▼                         │
└─────────────────────────────────────────────┘
```

### При клике на ▼:
```
┌─────────────────────────────────────────────┐
│ ER-BAT                      ✈️              │
│                          45,623.5 hrs       │
│                            28,450 cyc       │
│ ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ POSITION 1 - 880123                     │ │
│ │ ┌────────┐ TSN on A/C:    8,450.0 hrs  │ │
│ │ │░░░░░░░░│ CSN on A/C:    5,200 cyc    │ │
│ │ │░ENGINE░│ Total TSN:    23,450.0 hrs  │ │
│ │ │░░SVG░░░│ Total CSN:    14,200 cyc    │ │
│ │ │░ANIM░░░│ N1 Cruise:    85.0%         │ │
│ │ └────────┘ N1 Takeoff:   95.0%         │ │
│ │            N2 Cruise:    92.0%         │ │
│ │            N2 Takeoff:   98.0%         │ │
│ │            Installed:    2024-01-15    │ │
│ │            Last Update:  2024-11-30    │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ POSITION 2                              │ │
│ │         📭 No Engine Installed          │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ [... Positions 3 & 4 ...]                  │
│                                             │
│ ─────────────────────────────────────────── │
│                   ▲                         │
└─────────────────────────────────────────────┘
```

## 2. Цветовая схема

### Карточки самолетов:
- **Фон**: Темный градиент `#1a2332` → `#2d3e50`
- **Граница**: Светлая полупрозрачная `rgba(255,255,255,0.1)`
- **Тень**: Многослойная для 3D эффекта
- **При hover**: Подсвечивается синим `rgba(0,123,255,0.3)`

### Позиции двигателей:
- **Фон**: Еще темнее `#0f1419` → `#1e2835`
- **Заголовок**: Синий `#007bff` с underline
- **Важные данные**: Золото `#ffd700` (TSN/CSN on A/C)
- **Обычные данные**: Белый `#ffffff`
- **Лейблы**: Полупрозрачный серый `rgba(255,255,255,0.5)`

### SVG Двигатель:
- **Корпус**: Синий градиент `#1e3a8a` → `#3b82f6`
- **Вал**: Темный `#1e293b`
- **Индикатор**: Золотой `#fbbf24` (вращается 3 сек)

## 3. Боковое меню (Sidebar)

### Было:
```
Actions:
  - Shipment
  - Installation
  - Remove
  - Repair
  - Utilization
  - ENG Parameters

Inventory:
  - Parts Logistics
```

### Стало:
```
Actions:
  - Installation
  - Remove
  - Repair
  - Utilization
  - ENG Parameters

▶ Logistics:
    - Shipment
    - Parts Logistics
```

При клике на "▶ Logistics":
```
▼ Logistics:
    → Shipment
    → Parts Logistics
```

## 4. Анимации

### Expand/Collapse:
```
Timing: 0.5s cubic-bezier(0.4, 0, 0.2, 1)
Effect: Плавное разворачивание с изменением max-height
```

### Hover эффекты:
```css
/* Карточка поднимается */
transform: translateY(-4px);

/* Усиливается тень */
box-shadow: 0 12px 48px rgba(0,123,255,0.3);

/* Всё за 0.4s */
transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
```

### SVG Engine Rotation:
```xml
<circle cx="100" cy="90" r="3" fill="#fbbf24">
  <animateTransform 
    attributeName="transform" 
    type="rotate" 
    from="0 100 100" 
    to="360 100 100" 
    dur="3s" 
    repeatCount="indefinite"/>
</circle>
```

## 5. Расчет данных

### TSN on Aircraft (ключевая формула):
```python
# При установке (запоминаем):
engine.tsn_at_install = 15000.0  # Было 15,000 часов
engine.csn_at_install = 9000     # Было 9,000 циклов

# После 120 часов полетов на новом самолете:
engine.total_time = 15120.0      # Стало 15,120 часов

# На дашборде покажется:
TSN on A/C = 15120.0 - 15000.0 = 120.0 hrs ✅
CSN on A/C = 9120 - 9000 = 120 cyc ✅
```

### Автоматическое обновление при ATLB:
```python
# Ввели данные:
flight_hours = 5.5
cycles = 3

# Обновились автоматически:
aircraft.total_time += 5.5      # ✅
aircraft.total_cycles += 3      # ✅

# Для ВСЕХ установленных двигателей:
for engine in installed_engines:
    engine.total_time += 5.5    # ✅
    engine.total_cycles += 3    # ✅
```

## 6. Типографика

### Заголовки:
```css
font-size: 1.5rem
font-weight: 700
letter-spacing: normal
text-shadow: 0 2px 8px rgba(0,0,0,0.3)
```

### Данные (важные):
```css
font-size: 1.3rem
font-weight: 600
color: #ffd700  /* Золото */
```

### Данные (обычные):
```css
font-size: 1.1rem
font-weight: 600
color: #ffffff
```

### Лейблы:
```css
font-size: 0.75rem
color: rgba(255,255,255,0.5)
text-transform: uppercase
letter-spacing: 1px
```

## 7. Grid Layout

### Главный контейнер:
```html
<div class="row">
  <div class="col-lg-4 col-md-6">  <!-- 3 колонки на больших экранах -->
    [Aircraft Card]
  </div>
</div>
```

### Данные двигателя:
```css
display: grid;
grid-template-columns: repeat(2, 1fr);  /* 2 колонки */
gap: 15px;
```

## 8. Responsive Design

### Large screens (≥ 992px):
```
[Card 1] [Card 2] [Card 3]
```

### Medium screens (≥ 768px):
```
[Card 1] [Card 2]
[Card 3]
```

### Small screens (< 768px):
```
[Card 1]
[Card 2]
[Card 3]
```

---

## 🎯 Ключевые особенности

1. **Золотые цифры** - это TSN/CSN на конкретном самолете (главная метрика!)
2. **Белые цифры** - общий налет двигателя
3. **Синие заголовки** - номер позиции и S/N
4. **Анимация** - вращающаяся точка в SVG двигателя
5. **Expand/Collapse** - плавное разворачивание на 0.5 сек
6. **Hover** - карточки поднимаются и светятся

## 🚀 Взаимодействие

1. **Клик на ▼** → Раскрывается список двигателей
2. **Hover на карточке** → Карточка поднимается
3. **Ввод данных ATLB** → Автоматически обновляются все счетчики
4. **Refresh страницы** → Данные подгружаются с сервера

---

_Дизайн вдохновлен премиум авиационным софтом (Airbus Skywise, Boeing Analytics)_
