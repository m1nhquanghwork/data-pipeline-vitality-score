# PawHealthAI Vitality Score Engine

## What is the Vitality Score?
The Vitality Score is a 0-100 health tracking metric designed to help pet owners understand their pet's overall well-being. It is using the 4 weeks recorded data straight from PawHealthAI app. This Scoring system would help pet owners be able to keep on track with pet physical and mental health, and Evie (AI bot) be able to use this and give recommendation and advice if a particular action is needed.

## Data 
The data as being said above capture directly from the PawHealthAI app. The data collection are divdied into different data class:

### Pet Profile
This include any personal information from the pet inclding: pet name, birth, breed, postcode, streak (keep on track weekly checkin), consistency, worming compliant, vaccination current, last visit.

### Vet Interaction Log
This is the log of the vet toward pets, mostly captured by the vet and will record all observation from the vet visited.

### Dental Health Log
Design mainly for puppy teeth check-in which to keep on track of the pet dental health.

### Toileting Log
Mainly tracking bowel habits, frquency and acute overrides, this is for the purpose of tracking on digestion system and toilet habit of the pet.

### Check-in Data
The check-in data records all the pet's health data, including vet interation log, dental health log and toileting log. This is the main data for recording and calculating vitality score for pet.

## The Three-Layer System
The Vitality Score runs on a carefully designed architecture to ensure it is both smart and safe.

### Layer 1: The Wellness Trend Engine (The "Math")
This layer tracks general, day-to-day wellness based on weekly check-ins.
* **What it tracks:** It looks at factors like activity levels, energy, appetite, and sleep quality. 
* **Smart Adjustments:** The engine is customized for the pet's breed and age [cite: 560]. For example, high-energy breeds like Vizslas will have their activity levels weighted much more heavily than a low-energy breed. 
* **Signal vs. Noise:** The system knows the difference between a minor fluctuation and a real health issue. A single week of slightly reduced appetite is considered "noise" and won't severely penalize the score. However, reduced appetite combined with lower energy and a behavioral change is a "signal" that triggers a larger score drop.

### Layer 2: The Red Flag Engine (The "Safety Net")
This is the system's built-in safety mechanism. It handles acute or serious medical signs separately so they don't get lost in the general math.
* **Immediate Action:** If an owner logs a high-severity warning sign—such as blood in the stool or a sudden collapse in appetite combined with lethargy—this layer immediately takes over.
* **Bypassing the Math:** It completely bypasses the 0-100 scoring system and immediately places the pet into the "Action Needed" zone, prompting the owner to contact a vet.

### Layer 3: Clear, Cautious Explanations
PawHealthAI ensures that pet owners are never left guessing.
* **Evie's Explanations:** Every time the Vitality Score changes, the virtual assistant, Evie, explains exactly *why* in one simple sentence. For example: "Bonnie's score improved this week because her energy and appetite both returned to her normal range".
* **Safety First:** The system avoids making medical diagnoses (like guessing a dog has diabetes). Instead, it stays cautious and focuses on explaining the observed trends and recommending professional vet advice when necessary .

## The Health Zones
The score is visualized on a circular meter broken down into four color-coded zones:
* **Bright Green (85–100):** The pet is doing wonderfully. Consistently high scores may trigger community sharing prompts.
* **Medium Green (70–84):** The pet is tracking normally and maintaining standard wellness.
* **Watch Zone / Yellow (50–69):** The pet is below their usual baseline. Evie will prompt the owner to monitor closely and provide a link to book a vet visit via a directory.
* **Action Needed (Below 50):** Indicates a critical drop in wellness or a Red Flag trigger, prompting immediate vet contact. 