import pandas as pd
from ortools.sat.python import cp_model
import calendar
from datetime import date
import holidays

class ScheduleGenerator:
    def __init__(self, year, month, employees, unavailabilities, location_name="Maszynownia Przepompowni", prefer_whole_weekends_off=False):
        self.year = year
        self.month = month
        self.prefer_whole_weekends_off = prefer_whole_weekends_off
        self.num_days = calendar.monthrange(year, month)[1]
        self.employees = employees
        self.num_employees = len(employees)
        self.unavailabilities = unavailabilities  # dict: emp_idx -> {day_1_indexed: 'U' | 'CH' | 'W'}
        self.pl_holidays = holidays.Poland(years=self.year)
        self.location_name = location_name

        # Shift types
        # 0: Rano (6-14), 1: Popołudnie (14-22), 2: Noc (22-06)
        # 3: Wolne, 4: Urlop, 5: Chorobowe
        self.R, self.P, self.N, self.W, self.U, self.CH = 0, 1, 2, 3, 4, 5
        self.shift_names = {self.R: 'R', self.P: 'P', self.N: 'N', self.W: 'W', self.U: 'U', self.CH: 'CH'}

    def is_weekend_or_holiday(self, day):
        # day is 1-indexed
        dt = date(self.year, self.month, day)
        if dt.weekday() >= 5:
            return True
        if dt in self.pl_holidays:
            return True
        return False

    def solve(self):
        model = cp_model.CpModel()
        
        # Variables
        shifts = {}
        for e in range(self.num_employees):
            for d in range(1, self.num_days + 1):
                shifts[(e, d)] = model.NewIntVar(0, 5, f'shift_e{e}_d{d}')
                
        # Boolean variables for shifts
        shift_is = {}
        for e in range(self.num_employees):
            for d in range(1, self.num_days + 1):
                for s in range(6):
                    shift_is[(e, d, s)] = model.NewBoolVar(f'shift_is_e{e}_d{d}_s{s}')
                    model.Add(shifts[(e, d)] == s).OnlyEnforceIf(shift_is[(e, d, s)])
                    model.Add(shifts[(e, d)] != s).OnlyEnforceIf(shift_is[(e, d, s)].Not())
                    
                # Exactly one state per day handled implicitly by shifts integer variable
                model.AddExactlyOne([shift_is[(e, d, s)] for s in range(6)])

        extra_penalties = []

        # Fixed Unavailabilities
        self.ignored_vars = {}
        for e in range(self.num_employees):
            for d in range(1, self.num_days + 1):
                is_u = False
                is_ch = False
                if e in self.unavailabilities and d in self.unavailabilities[e]:
                    status = self.unavailabilities[e][d]
                    if status == 'U':
                        model.Add(shifts[(e, d)] == self.U)
                        is_u = True
                    elif status == 'CH':
                        model.Add(shifts[(e, d)] == self.CH)
                        is_ch = True
                    else:
                        ignored_var = model.NewBoolVar(f'ignored_{e}_{d}')
                        self.ignored_vars[(e, d)] = ignored_var
                        extra_penalties.append(ignored_var * 50000)
                        
                        if status == 'W':
                            model.Add(shifts[(e, d)] == self.W).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] != self.W).OnlyEnforceIf(ignored_var)
                        elif status == 'NR':
                            model.Add(shifts[(e, d)] != self.R).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] == self.R).OnlyEnforceIf(ignored_var)
                        elif status == 'NP':
                            model.Add(shifts[(e, d)] != self.P).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] == self.P).OnlyEnforceIf(ignored_var)
                        elif status == 'NN':
                            model.Add(shifts[(e, d)] != self.N).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] == self.N).OnlyEnforceIf(ignored_var)
                        elif status == 'TR' or status == 'R':
                            model.Add(shifts[(e, d)] == self.R).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] != self.R).OnlyEnforceIf(ignored_var)
                        elif status == 'TP' or status == 'P':
                            model.Add(shifts[(e, d)] == self.P).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] != self.P).OnlyEnforceIf(ignored_var)
                        elif status == 'TN' or status == 'N':
                            model.Add(shifts[(e, d)] == self.N).OnlyEnforceIf(ignored_var.Not())
                            model.Add(shifts[(e, d)] != self.N).OnlyEnforceIf(ignored_var)
                
                # Prevent generator from randomly assigning U or CH
                if not is_u:
                    model.Add(shifts[(e, d)] != self.U)
                if not is_ch:
                    model.Add(shifts[(e, d)] != self.CH)

        # Kary dodatkowe (preferencje użytkownika)

        # Basic Coverage Rules 
        for d in range(1, self.num_days + 1):
            r_count = sum(shift_is[(e, d, self.R)] for e in range(self.num_employees))
            p_count = sum(shift_is[(e, d, self.P)] for e in range(self.num_employees))
            n_count = sum(shift_is[(e, d, self.N)] for e in range(self.num_employees))
            
            is_we = self.is_weekend_or_holiday(d)

            if "Oczyszczalnia" in self.location_name:
                # Nocna - tylko 1
                model.Add(n_count == 1)
                
                if is_we:
                    # W weekendy i święta staramy się robić tylko pojedyncze zmiany (1-1-1)
                    model.Add(r_count == 1)
                    model.Add(p_count == 1)
                else:
                    # Dni powszednie: prefereowane R=3, P=2. 
                    # "zamiast 4 rano lepiej zeby było 2 popołudniu" -> twardy limit P na 2, R na 4
                    model.Add(p_count >= 1)
                    model.Add(p_count <= 2)
                    model.Add(r_count >= 2) # minimum 2 na rano
                    model.Add(r_count <= 4)
                    
                    # Kara za 4 osoby na rano (preferujemy 3)
                    r4 = model.NewBoolVar(f'loc_{self.location_name}_r4_d{d}')
                    model.Add(r_count == 4).OnlyEnforceIf(r4)
                    model.Add(r_count != 4).OnlyEnforceIf(r4.Not())
                    extra_penalties.append(r4 * 200)
                    
                    # Bonus za 2 osoby na popołudniu (kara jeśli tylko 1)
                    p1 = model.NewBoolVar(f'loc_{self.location_name}_p1_d{d}')
                    model.Add(p_count == 1).OnlyEnforceIf(p1)
                    model.Add(p_count != 1).OnlyEnforceIf(p1.Not())
                    extra_penalties.append(p1 * 150) 
            else:
                # Domyślne dla Maszynownia Przepompowni
                model.Add(n_count == 1)
                model.Add(p_count == 1)
                model.Add(r_count >= 1)
                
                dt_curr = date(self.year, self.month, d)
                if dt_curr in self.pl_holidays or dt_curr.weekday() == 6: # niedziele i święta
                    model.Add(r_count <= 1)
                elif dt_curr.weekday() == 5: # soboty (ostateczność 2)
                    model.Add(r_count <= 2)
                else:
                    model.Add(r_count <= 3)

        # Rest Rules (Kodeks Pracy)
        for e in range(self.num_employees):
            for d in range(1, self.num_days):
                # (P, R) forbidden - 8h rest < 11h
                model.AddImplication(shift_is[(e, d, self.P)], shift_is[(e, d + 1, self.R)].Not())
                # (N, R) forbidden - 0h rest < 11h
                model.AddImplication(shift_is[(e, d, self.N)], shift_is[(e, d + 1, self.R)].Not())
                # (N, P) forbidden - 8h rest < 11h
                model.AddImplication(shift_is[(e, d, self.N)], shift_is[(e, d + 1, self.P)].Not())

        # Obliczenie normy czasu pracy na dany miesiąc
        norm_days = 0
        for d in range(1, self.num_days + 1):
            dt = date(self.year, self.month, d)
            if dt.weekday() < 5:
                norm_days += 1
                
        # Święta wypadające w inne dni niż niedziela obniżają wymiar
        for d in range(1, self.num_days + 1):
            dt = date(self.year, self.month, d)
            if dt in self.pl_holidays and dt.weekday() != 6:
                norm_days -= 1
        
        r_counts = []
        p_counts = []
        n_counts = []
        w_counts = []
        we_counts = []
        we_penalties = []
        
        for e in range(self.num_employees):
            r_c = sum(shift_is[(e, d, self.R)] for d in range(1, self.num_days + 1))
            p_c = sum(shift_is[(e, d, self.P)] for d in range(1, self.num_days + 1))
            n_c = sum(shift_is[(e, d, self.N)] for d in range(1, self.num_days + 1))
            w_c = sum(shift_is[(e, d, self.W)] for d in range(1, self.num_days + 1))
            u_c = sum(shift_is[(e, d, self.U)] for d in range(1, self.num_days + 1))
            ch_c = sum(shift_is[(e, d, self.CH)] for d in range(1, self.num_days + 1))
            
            r_counts.append(r_c)
            p_counts.append(p_c)
            n_counts.append(n_c)
            w_counts.append(w_c)
            
            # Wymuszenie sumy przepracowanych dni (godzin łącznie z u i ch) do normy wymiaru
            model.Add(r_c + p_c + n_c + u_c + ch_c == norm_days)
            
            # Weekend & holiday logic
            sundays = []
            we_shifts = []
            we_r_shifts = []
            we_p_shifts = []
            we_n_shifts = []
            
            for d in range(1, self.num_days + 1):
                dt = date(self.year, self.month, d)
                if dt.weekday() == 6:
                    sundays.append(d)
                
                if self.is_weekend_or_holiday(d):
                    we_shifts.append(shift_is[(e, d, self.R)])
                    we_shifts.append(shift_is[(e, d, self.P)])
                    we_shifts.append(shift_is[(e, d, self.N)])
                    we_r_shifts.append(shift_is[(e, d, self.R)])
                    we_p_shifts.append(shift_is[(e, d, self.P)])
                    we_n_shifts.append(shift_is[(e, d, self.N)])
            
            # Przynajmniej jedna wolna niedziela w miesiącu dla pracownika (wymóg KP o wolnej niedzieli co 4 tygodnie)
            if sundays:
                sunday_work = sum(shift_is[(e, d, self.R)] + shift_is[(e, d, self.P)] + shift_is[(e, d, self.N)] for d in sundays)
                model.Add(sunday_work <= len(sundays) - 1)
                
            we_counts.append(sum(we_shifts))
            
            # Urozmaicenie zmian w weekendy (penalizacja przewagi jednego typu zmiany - szukamy różnorodności)
            e_max_we_shift = model.NewIntVar(0, 31, f'e_{e}_max_we_shift')
            e_min_we_shift = model.NewIntVar(0, 31, f'e_{e}_min_we_shift')
            model.AddMaxEquality(e_max_we_shift, [sum(we_r_shifts), sum(we_p_shifts), sum(we_n_shifts)])
            model.AddMinEquality(e_min_we_shift, [sum(we_r_shifts), sum(we_p_shifts), sum(we_n_shifts)])
            we_penalties.append(e_max_we_shift - e_min_we_shift)
            
            # Wymuszenie sumy przepracowanych dni (godzin łącznie z u i ch) do normy wymiaru
            model.Add(r_c + p_c + n_c + u_c + ch_c == norm_days)
 
        # Objective: minimize differences between max and min of each shift type to ensure equality
        max_r = model.NewIntVar(0, 31, 'max_r')
        min_r = model.NewIntVar(0, 31, 'min_r')
        model.AddMaxEquality(max_r, r_counts)
        model.AddMinEquality(min_r, r_counts)
 
        max_p = model.NewIntVar(0, 31, 'max_p')
        min_p = model.NewIntVar(0, 31, 'min_p')
        model.AddMaxEquality(max_p, p_counts)
        model.AddMinEquality(min_p, p_counts)
 
        max_n = model.NewIntVar(0, 31, 'max_n')
        min_n = model.NewIntVar(0, 31, 'min_n')
        model.AddMaxEquality(max_n, n_counts)
        model.AddMinEquality(min_n, n_counts)
 
        # 7-day windows - user rule:
        # W każdym bloku 7-dniowym pracownik musi mieć odpowiedni odpoczynek tygodniowy.
        # Odpoczynek spełniony gdy: 2 dni z rzędu wolne (W, U, CH) LUB 1 dzień wolnego pomiędzy różnymi zmianami roboczymi (np. R,W,P lub N,W,R).
        periods = [(1, 7), (8, 14), (15, 21), (22, self.num_days)]
        
        for e in range(self.num_employees):
            # Rolling 7-day window max working days (pozostałość dla bezpieczeństwa)
            for d in range(1, self.num_days - 5):
                working_days = sum(shift_is[(e, d+offset, s)] for offset in range(7) for s in [self.R, self.P, self.N])
                model.Add(working_days <= 6)

            # --- Nowa reguła 35h odpoczynku tygodniowego ---
            e_is_off = {}
            for d in range(1, self.num_days + 1):
                e_is_off[d] = model.NewBoolVar(f'is_off_{e}_{d}')
                model.Add(shift_is[(e, d, self.W)] + shift_is[(e, d, self.U)] + shift_is[(e, d, self.CH)] == 1).OnlyEnforceIf(e_is_off[d])
                model.Add(shift_is[(e, d, self.W)] + shift_is[(e, d, self.U)] + shift_is[(e, d, self.CH)] == 0).OnlyEnforceIf(e_is_off[d].Not())
                
            two_days_off = {}
            for d in range(1, self.num_days):
                two_days_off[d] = model.NewBoolVar(f'two_days_off_{e}_{d}')
                model.AddBoolAnd([e_is_off[d], e_is_off[d+1]]).OnlyEnforceIf(two_days_off[d])
                model.AddBoolOr([e_is_off[d].Not(), e_is_off[d+1].Not()]).OnlyEnforceIf(two_days_off[d].Not())
                
            different_shifts = {}
            for d in range(2, self.num_days):
                same_working = model.NewBoolVar(f'same_working_{e}_{d}')
                sw_r = model.NewBoolVar(f'sw_r_{e}_{d}')
                sw_p = model.NewBoolVar(f'sw_p_{e}_{d}')
                sw_n = model.NewBoolVar(f'sw_n_{e}_{d}')
                
                model.AddBoolAnd([shift_is[(e, d-1, self.R)], shift_is[(e, d+1, self.R)]]).OnlyEnforceIf(sw_r)
                model.AddBoolOr([shift_is[(e, d-1, self.R)].Not(), shift_is[(e, d+1, self.R)].Not()]).OnlyEnforceIf(sw_r.Not())
                
                model.AddBoolAnd([shift_is[(e, d-1, self.P)], shift_is[(e, d+1, self.P)]]).OnlyEnforceIf(sw_p)
                model.AddBoolOr([shift_is[(e, d-1, self.P)].Not(), shift_is[(e, d+1, self.P)].Not()]).OnlyEnforceIf(sw_p.Not())
                
                model.AddBoolAnd([shift_is[(e, d-1, self.N)], shift_is[(e, d+1, self.N)]]).OnlyEnforceIf(sw_n)
                model.AddBoolOr([shift_is[(e, d-1, self.N)].Not(), shift_is[(e, d+1, self.N)].Not()]).OnlyEnforceIf(sw_n.Not())
                
                # same_working jest 1, gdy d-1 i d+1 to te same zmiany robocze (R-R, P-P, N-N)
                model.AddBoolOr([sw_r, sw_p, sw_n]).OnlyEnforceIf(same_working)
                model.AddBoolAnd([sw_r.Not(), sw_p.Not(), sw_n.Not()]).OnlyEnforceIf(same_working.Not())
                
                different_shifts[d] = model.NewBoolVar(f'different_shifts_{e}_{d}')
                # Warunek: dzień jest wolny(W), d-1 to roboczy, d+1 to roboczy, i SĄ RÓŻNE
                model.AddBoolAnd([
                    e_is_off[d],
                    e_is_off[d-1].Not(),
                    e_is_off[d+1].Not(),
                    same_working.Not()
                ]).OnlyEnforceIf(different_shifts[d])
                model.AddBoolOr([
                    e_is_off[d].Not(),
                    e_is_off[d-1],
                    e_is_off[d+1],
                    same_working
                ]).OnlyEnforceIf(different_shifts[d].Not())
                
            rest_anchors = {}
            for d in range(1, self.num_days + 1):
                rest_anchors[d] = model.NewBoolVar(f'rest_anchor_{e}_{d}')
                literals = []
                if d in two_days_off: literals.append(two_days_off[d])
                if d in different_shifts: literals.append(different_shifts[d])
                
                if literals:
                    model.AddBoolOr(literals).OnlyEnforceIf(rest_anchors[d])
                    model.AddBoolAnd([lit.Not() for lit in literals]).OnlyEnforceIf(rest_anchors[d].Not())
                else:
                    model.Add(rest_anchors[d] == 0)
                    
            for p_idx, (p_start, p_end) in enumerate(periods):
                period_anchors = [rest_anchors[d] for d in range(p_start, p_end + 1)]
                period_satisfied = model.NewBoolVar(f'period_sat_{e}_{p_start}')
                model.AddBoolOr(period_anchors).OnlyEnforceIf(period_satisfied)
                model.AddBoolAnd([a.Not() for a in period_anchors]).OnlyEnforceIf(period_satisfied.Not())
                
                # Priorytet najwyższy (100k) nakłaniający solver do respektowania przerwy tygodniowej ponad życzeniami użytkownika
                extra_penalties.append(period_satisfied.Not() * 100000)
                
        # Kary dodatkowe (preferencje użytkownika) - kontynuacja dla domyślnych
        for d in range(1, self.num_days + 1):
            r_count_val = sum(shift_is[(e, d, self.R)] for e in range(self.num_employees))
            dt_curr = date(self.year, self.month, d)
            
            if dt_curr.weekday() < 5 and dt_curr not in self.pl_holidays:
                # W tygodniu preferujemy 2 lub 3 osoby na rano, unikamy pojedynczych obsad
                is_single = model.NewBoolVar(f'week_single_r_d{d}')
                model.Add(r_count_val <= 1).OnlyEnforceIf(is_single)
                model.Add(r_count_val > 1).OnlyEnforceIf(is_single.Not())
                extra_penalties.append(is_single * 1000)  # Potężna kara za pojedynczą zmianę R w tygodniu
                
            elif dt_curr.weekday() == 5 and dt_curr not in self.pl_holidays:
                # W soboty preferujemy 1 osobę na rano, podwójne zmiany to ostateczność
                is_double = model.NewBoolVar(f'sat_double_r_d{d}')
                model.Add(r_count_val == 2).OnlyEnforceIf(is_double)
                model.Add(r_count_val != 2).OnlyEnforceIf(is_double.Not())
                extra_penalties.append(is_double * 500)  # Potężna kara zniechęcająca do podwójnych rannych w sobotę

        if getattr(self, 'prefer_whole_weekends_off', False):
            for e in range(self.num_employees):
                for d in range(1, self.num_days):
                    dt = date(self.year, self.month, d)
                    if dt.weekday() == 5:  # Sobota, d+1 to Niedziela
                        sat_work = model.NewBoolVar(f'sat_work_e{e}_d{d}')
                        sun_work = model.NewBoolVar(f'sun_work_e{e}_d{d+1}')
                        
                        model.Add(shift_is[(e, d, self.W)] + shift_is[(e, d, self.U)] + shift_is[(e, d, self.CH)] == 0).OnlyEnforceIf(sat_work)
                        model.Add(shift_is[(e, d, self.W)] + shift_is[(e, d, self.U)] + shift_is[(e, d, self.CH)] == 1).OnlyEnforceIf(sat_work.Not())
                        
                        model.Add(shift_is[(e, d+1, self.W)] + shift_is[(e, d+1, self.U)] + shift_is[(e, d+1, self.CH)] == 0).OnlyEnforceIf(sun_work)
                        model.Add(shift_is[(e, d+1, self.W)] + shift_is[(e, d+1, self.U)] + shift_is[(e, d+1, self.CH)] == 1).OnlyEnforceIf(sun_work.Not())
                        
                        one_day_work = model.NewBoolVar(f'one_day_we_work_e{e}_d{d}')
                        model.Add(sat_work + sun_work == 1).OnlyEnforceIf(one_day_work)
                        model.Add(sat_work + sun_work != 1).OnlyEnforceIf(one_day_work.Not())
                        
                        extra_penalties.append(one_day_work * 800)  # Duża kara za rozbijanie weekendu

        max_we = model.NewIntVar(0, 31, 'max_we')
        min_we = model.NewIntVar(0, 31, 'min_we')
        model.AddMaxEquality(max_we, we_counts)
        model.AddMinEquality(min_we, we_counts)

        # Penalties: favor less total diffs + user preferences + weekend equality
        model.Minimize(
            (max_n - min_n) * 10 + 
            (max_r - min_r) * 2 + 
            (max_p - min_p) * 2 + 
            (max_we - min_we) * 15 +  # silny nacisk na równy podział weekendów 
            sum(we_penalties) * 5 +   # średni nacisk na różnorodność zmian w weekendy
            sum(extra_penalties)
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            result = {}
            ignored_requests = []
            for e in range(self.num_employees):
                emp_name = self.employees[e]
                result[emp_name] = {}
                for d in range(1, self.num_days + 1):
                    val = solver.Value(shifts[(e, d)])
                    result[emp_name][d] = self.shift_names[val]
                    
                    if (e, d) in getattr(self, 'ignored_vars', {}) and solver.Value(self.ignored_vars[(e, d)]):
                        ignored_requests.append({
                            'Pracownik': emp_name,
                            'Dzień': d,
                            'Prośba': self.unavailabilities[e][d],
                            'Przydzielono': self.shift_names[val]
                        })
            return result, ignored_requests
        else:
            return None, []
