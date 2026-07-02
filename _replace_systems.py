import sys

with open(sys.argv[1], encoding="utf-8") as f:
    content = f.read()

start = content.find("async def _load_facilities")
end = content.find("def _clear_search")  # go to the last function in the file

# Keep everything before facilities, and replace with systems
prefix = content[:start]

new_code = '''    # ------------------------
    #  Systems
    # ------------------------

    async def _load_systems(self):
        loop = asyncio.get_event_loop()
        try:
            systems = await loop.run_in_executor(self._executor, self._db_get_systems)
        except Exception:
            systems = []

        options = [ft.DropdownOption("none", "无（不计安装费）")]
        for sys_ in systems:
            label = f"{sys_['name']} (指数 {sys_['cost_index']})"
            val = f"{sys_['name']}|{sys_['cost_index']}"
            options.append(ft.DropdownOption(val, label))
        self._system_dropdown.options = options
        self._system_dropdown.value = "none"
        self._page.update()

    def _db_get_systems(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT solar_system_id, cost_index
                FROM industry_system_costs
                WHERE activity = 'manufacturing'
                ORDER BY cost_index ASC
                LIMIT 30
            """)
            rows = c.fetchall()
            result = []
            for sid, cost in rows:
                c2 = conn.cursor()
                c2.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (sid,))
                name_row = c2.fetchone()
                name = "?"
                if name_row:
                    name = name_row[0] or name_row[1] or str(sid)
                result.append({"system_id": sid, "cost_index": cost, "name": name})
            return result
        finally:
            conn.close()
'''

# Find the end of the facilities section: the next def after _clear_search
rest = content[end:]  # keep _clear_search and RIGHT constant

with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(prefix + new_code + rest)

print("Replaced facilities with systems")
