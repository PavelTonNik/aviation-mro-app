# Aviation Dashboard - Автоматический расчет налета двигателей

## Что реализовано

### 1. Backend (база данных и API)

#### Новые поля в таблице `engines`:
- `tsn_at_install` - TSN (Total Since New) на момент установки двигателя
- `csn_at_install` - CSN (Cycles Since New) на момент установки
- `install_date` - Дата установки двигателя на самолет

#### Логика работы:

**При установке двигателя (Installation):**
```python
eng.tsn_at_install = data.tt  # Запоминаем текущий TSN
eng.csn_at_install = data.tc  # Запоминаем текущий CSN
eng.install_date = func.now() # Фиксируем дату установки
```

**При добавлении данных из бортжурнала (Utilization/ATLB):**
```python
# Обновляем общий налет самолета
aircraft.total_time += flight_hours
aircraft.total_cycles += cycles

# Обновляем налет ВСЕХ установленных двигателей
for engine in installed_engines:
    engine.total_time += flight_hours
    engine.total_cycles += cycles
```

**Расчет налета на конкретном самолете:**
```python
tsn_on_aircraft = engine.total_time - engine.tsn_at_install
csn_on_aircraft = engine.total_cycles - engine.csn_at_install
```

### 2. Frontend (главный дашборд)

#### Новый дизайн карточек самолетов:

**Структура карточки:**
```
┌─────────────────────────────────────┐
│ ER-BAT          ✈️ 45,623.5 hrs    │
│                    28,450 cyc       │
├─────────────────────────────────────┤
│      [Свернутые позиции]            │
├─────────────────────────────────────┤
│              ▼ (кнопка)             │
└─────────────────────────────────────┘
```

**При разворачивании (клик на ▼):**
```
┌─────────────────────────────────────┐
│ Position 1 - 880123                 │
│ ┌────────┐  TSN on A/C:  8,450.0   │
│ │        │  CSN on A/C:  5,200     │
│ │ [SVG]  │  Total TSN:   23,450.0  │
│ │ Engine │  Total CSN:   14,200    │
│ │        │  N1 Cruise:   85.0%     │
│ └────────┘  N1 Takeoff:  95.0%     │
│             N2 Cruise:   92.0%      │
│             N2 Takeoff:  98.0%      │
│             Installed:   2024-01-15 │
│             Last Update: 2024-11-30 │
└─────────────────────────────────────┘
```

#### Особенности дизайна:
- **Темная премиум-палитра**: градиенты от #1a2332 до #2d3e50
- **Золотые акценты**: налет самолета и TSN/CSN на самолете
- **Анимация двигателя**: SVG с вращающимся индикатором
- **Плавные переходы**: expand/collapse с cubic-bezier анимацией
- **Профессиональные тени**: многослойные box-shadow для глубины
- **Hover эффекты**: карточки поднимаются и светятся при наведении

### 3. API Endpoints

#### `GET /api/dashboard/aircraft-details`
Возвращает полную информацию для дашборда:
```json
[
  {
    "aircraft_id": 1,
    "tail_number": "ER-BAT",
    "model": "Boeing 747-200",
    "total_time": 45623.5,
    "total_cycles": 28450,
    "positions": [
      {
        "engine_id": 5,
        "original_sn": "880123",
        "current_sn": "880123",
        "total_tsn": 23450.0,
        "total_csn": 14200,
        "tsn_on_aircraft": 8450.0,
        "csn_on_aircraft": 5200,
        "n1_takeoff": 95.0,
        "n1_cruise": 85.0,
        "n2_takeoff": 98.0,
        "n2_cruise": 92.0,
        "install_date": "2024-01-15",
        "last_update": "2024-11-30 14:25"
      },
      null,  // Position 2 пустая
      null,  // Position 3 пустая
      null   // Position 4 пустая
    ]
  }
]
```

## Как это работает (пример):

### Сценарий 1: Новый двигатель с нулевым налетом
1. Собрали двигатель после ремонта → TSN = 0, CSN = 0
2. Установили на ER-BAT → `tsn_at_install = 0`, `csn_at_install = 0`
3. Внесли данные из ATLB: +5.5 часов, +3 цикла
4. **Результат:**
   - Total TSN: 5.5 hrs
   - TSN on Aircraft: 5.5 hrs (5.5 - 0)

### Сценарий 2: Двигатель с наработкой
1. Двигатель уже налетал 15,000 hrs / 9,000 cyc
2. Установили на ER-BAR → `tsn_at_install = 15000`, `csn_at_install = 9000`
3. ER-BAR налетал еще 120 часов после установки
4. **Результат:**
   - Total TSN: 15,120 hrs
   - TSN on Aircraft: 120 hrs (15120 - 15000)

## Файлы изменены:

1. **backend/models.py** - добавлены поля tsn_at_install, csn_at_install, install_date
2. **backend/main.py** - 
   - Обновлена функция `install_engine()` для сохранения snapshot
   - Добавлен endpoint `GET /api/dashboard/aircraft-details`
3. **frontend/index.html** - 
   - Новые CSS стили для премиум-карточек
   - JavaScript для expand/collapse анимации
   - SVG анимация двигателя
4. **migrate_db.py** - миграция базы данных
5. **add_test_data.py** - скрипт для добавления демо-данных

## Запуск и тестирование:

```bash
# 1. Миграция базы (уже выполнена)
python migrate_db.py

# 2. Добавить тестовые данные (опционально)
python add_test_data.py

# 3. Запустить сервер
START.bat

# 4. Открыть http://localhost:8000
```

## Автоматические расчеты:

✅ При каждом добавлении данных в Utilization/ATLB:
- Обновляется общий налет самолета
- Обновляется налет всех установленных двигателей
- Автоматически пересчитывается TSN/CSN на самолете для каждого двигателя
- Сохраняется timestamp последнего обновления

✅ Дашборд показывает в реальном времени:
- Общий налет самолета (справа вверху)
- Для каждого двигателя:
  - TSN/CSN с момента установки (золотые цифры)
  - Общий TSN/CSN двигателя
  - N1/N2 параметры
  - Дату установки
  - Дату последнего обновления

## Особенности реализации:

- **4 позиции на каждом самолете** (747 имеет 4 двигателя)
- **Пустые позиции** отображаются с иконкой inbox
- **Плавная анимация** разворачивания (0.5s cubic-bezier)
- **SVG двигатель** с вращающейся точкой (3s loop)
- **Адаптивная сетка** (col-lg-4 для широких экранов)
- **Профессиональная типографика** с letter-spacing и shadows
