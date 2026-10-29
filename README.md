# NAPA-1 Re-entry Monitor

ระบบติดตามการลดระดับวงโคจรและประเมินเวลา/จุดกลับเข้าสู่ชั้นบรรยากาศของดาวเทียม NAPA-1 (NORAD 46320)
ข้อมูลอัปเดตอัตโนมัติทุก 2 ชั่วโมงด้วย GitHub Actions

## ขั้นตอน deploy (ครั้งเดียว ~10 นาที)

1. **สร้าง repository**: ล็อกอิน github.com → ปุ่ม **New** → ตั้งชื่อ เช่น `napa1-reentry` → เลือก **Public** → **Create repository**
2. **อัปโหลดไฟล์**: ในหน้า repo กด **uploading an existing file** → ลากไฟล์และโฟลเดอร์ทั้งหมดในโฟลเดอร์นี้ลงไป (`index.html`, `README.md`, `.nojekyll`, โฟลเดอร์ `data`, `scripts`, `.github`) → **Commit changes**
   - ถ้าโฟลเดอร์ `.github` ไม่ขึ้น (Mac/Windows ซ่อนโฟลเดอร์ที่ขึ้นต้นด้วยจุด): กด **Add file → Create new file** พิมพ์ชื่อ `.github/workflows/update.yml` แล้วคัดลอกเนื้อหาจากไฟล์ `update.yml` มาวาง → **Commit**
3. **เปิด Pages**: **Settings → Pages → Build and deployment → Source** เลือก **GitHub Actions**
4. **ให้สิทธิ์ Actions เขียนข้อมูล**: **Settings → Actions → General → Workflow permissions** เลือก **Read and write permissions** → Save
5. **รันครั้งแรก**: แท็บ **Actions** → เลือก **Update data & deploy** → **Run workflow**
6. รอ 1–2 นาที เว็บจะอยู่ที่ `https://<ชื่อผู้ใช้ GitHub>.github.io/napa1-reentry/`

หลังจากนี้ระบบจะดึงข้อมูลใหม่และ deploy เองทุก 2 ชม. ไม่ต้องทำอะไรเพิ่ม

## (ไม่บังคับ) ดึง TLE ย้อนหลังจาก Space-Track อัตโนมัติ

**Settings → Secrets and variables → Actions → New repository secret** เพิ่ม 2 ค่า:
- `ST_USER` = username ของ space-track.org
- `ST_PASS` = password

ทุกรอบจะดึง TLE ย้อนหลัง 10 วันมาเพิ่ม ทำให้การ fit แม่นขึ้น (รหัสผ่านถูกเข้ารหัสเก็บใน GitHub ไม่ปรากฏในไฟล์หรือ log)

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `index.html` | หน้า dashboard (ไฟล์เดียวจบ) |
| `data/tle.json` | TLE ทุกชุดที่เก็บได้ (สะสมเรื่อยๆ) |
| `data/apsis.json` | ประวัติ apogee/perigee จาก CelesTrak (เม.ย. 2567 – ต.ค. 2569) |
| `data/wx.json` | F10.7 รายวัน, ค่าเฉลี่ย 90 วัน, Kp จาก NOAA |
| `data/status.json` | เวลาที่อัปเดตล่าสุด, วันตกทางการ (ถ้ามี) |
| `scripts/update_data.py` | สคริปต์ดึงข้อมูล (Python ล้วน ไม่ต้องติดตั้งอะไร) |
| `.github/workflows/update.yml` | ตั้งเวลารันทุก 2 ชม. + deploy |

## หมายเหตุ

- ค่าพยากรณ์เป็นการประมาณเชิงวิศวกรรม ใช้คู่กับ TIP ของ Space-Track / Aerospace CORDS ก่อนรายงานทางการ
- repo แบบ Public: ใครมีลิงก์ก็เปิดได้ (ข้อมูลทั้งหมดเป็นข้อมูลเปิดสาธารณะ)
- หลังดาวเทียมตกแล้ว ปิดการอัปเดตได้ที่ **Actions → Update data & deploy → ⋯ → Disable workflow**
