# MEMORY.md - Long-Term Memory

## Identity
 
<add persistent identity details here for the agent> 

### Communication & Interaction Preferences
- Prefers to tell Clawdia todos directly via Telegram → Clawdia adds them to Todo.md manually
- Morning digest is very useful ("gentle nagging" works for her)
- Calendar events should be in **Sydney (AEST) timezone** — reminders 24 hours in advance
- Email labels can stay on emails after processing (useful for sorting in Outlook)
- Gentle nudges are welcome; doesn't need to be asked permission for internal work

---

## Household

- **People:**  
- **Kids:**  
- **Pets:**
- **Appliances:**  
- **Printer:**  
 

## Professional / Research

- Works with/at **<detail here> **  
- **Research focus:**  
- **Professional contacts mentioned:**  
- **Regularly reads:** 


---

## Grocery Preferences

- **Primary store:**  
- **Also shops at:**  
- **Workflow:** Agent maintains grocery list → builds price comparison → human places order
 
### Dietary / Quality Rules
- **Meat:** must be free range (except processed meats — preference free range, then Australian)
- **Milk:** must be free range
- **Allergies:** 
- **Other preferences:**

---

## Setup History
 
---

## Cron Jobs

<ask agent to add details to memory for each cron job, for example: > 

### morning-digest (ID: 16c48b00-559f-4bc7-9c9b-2c7120d83e00)
- Runs daily 8:30am AEST → Telegram to 8437776204
- Reads Bills.md and Todo.md; sends digest of upcoming bills + pending todos
- lightContext: true, timeout: 180s, model: deepseek-v4-pro
 
### ai-conferences-weekly (ID: f72a846f-5925-4845-ab3c-0832c283cbd3)
- Runs Sundays 2pm AEST → Telegram  
- Files: AI_Conferences_2026.md, AI_Conferences_2026.csv, AI_Conferences_Archive.md
- Compact .md format; past conferences auto-archived each run
- Timeout: 900s 
 
### weekly-cleaning-planner-print (no ID recorded yet)
- Prints Home_Cleaning_Weekly_Planner.md to HP printer Monday 6:30am
- Set up 2026-06-09; verify ID if needed

---

## Gmail & Calendar Setup

- **Gmail:**   
- **gog auth client:** "openclaw" (credentials at ~/Library/Application Support/gogcli/credentials-openclaw.json, also copied to default)
- **GCP project:**  
- **Tailscale Funnel**  
- **Pub/Sub topic:**  
- **Push subscription:** 
- **Google Calendar Family:** 
- **Google Calendar Personal:**   
- **Calendar timezone:**  
---

## Workspace Files

- **Bills.md** — bill tracker (Upcoming & Unpaid / Paid sections)
- **Todo.md** — action items; user tells agent todos directly via Telegram
- **todo_processed_ids.json** — processed email IDs for deduplication
- **Groceries.md** — current grocery list (managed via grocery-manager skill) 
- **AI_Conferences_2026.md / .csv** — conference list (compact format)  
