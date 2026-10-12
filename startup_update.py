"""Update before exposing editable user input; never close another GUI."""
from __future__ import annotations
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import app_updater
from update_storage import write_json


def startup_check(emit, cancelled):
    emit({'operation':'检查已签名的程序更新'})
    if cancelled.is_set():
        return 'cancelled'
    try:
        result=app_updater._stage_app_update(restart_after_install=True,progress=emit)
        if cancelled.is_set() or result.get('app')=='startup_cancelled':
            write_json(app_updater._data_dir()/'startup_restart_cancelled.json',
                       {'parent_pid':os.getpid(),'cancelled':True})
            return 'cancelled'
        write_json(app_updater._data_dir()/'app_update_launch_status.json',result)
        if result.get('app') in {'installation_staged','waiting_for_app_exit'}:
            emit({'operation':'更新已验证，正在自动安装并重新进入程序'})
            return 'handoff'
        emit({'operation':'程序版本检查完成，正在进入主界面'})
        return 'continue'
    except Exception as exc:
        # Keep the working app available, but do not clear legal findings or
        # claim the failed update succeeded. No raw exception/config exported.
        write_json(app_updater._data_dir()/'startup_update_status.json',
                   {'state':'failed','failure_type':type(exc).__name__,'fallback':'current_app'})
        emit({'operation':'程序更新暂未完成，自动保留当前版本；法律核验仍会执行'})
        return 'continue'


class StartupUpdateWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Policy Amadeus · 启动更新')
        self.configure(bg='#0e141b')
        self.geometry('600x240')
        self.minsize(480,240)
        self.result='cancelled'
        self.events=queue.Queue()
        self.cancelled=threading.Event()
        write_json(app_updater._data_dir()/'startup_restart_cancelled.json',{'parent_pid':os.getpid(),'cancelled':False})
        self.operation=tk.StringVar(value='正在准备启动更新…')
        tk.Label(self,text='Policy Amadeus',font=('Segoe UI',22,'bold'),bg='#0e141b',fg='#e5ecf1').pack(anchor='w',padx=28,pady=(24,12))
        self.operation_label=tk.Label(self,textvariable=self.operation,font=('Microsoft YaHei UI',11),bg='#0e141b',fg='#e5ecf1',wraplength=535,justify='left')
        self.operation_label.pack(anchor='w',padx=28)
        self.bind('<Configure>',lambda event:self.operation_label.configure(wraplength=max(1,event.width-56)) if event.widget is self else None)
        style=ttk.Style(self)
        style.theme_use('clam')
        style.configure('Startup.Horizontal.TProgressbar',background='#d98438',troughcolor='#1c2732',borderwidth=0)
        self.bar=ttk.Progressbar(self,mode='indeterminate',style='Startup.Horizontal.TProgressbar')
        self.bar.pack(fill='x',padx=28,pady=16)
        self.bar.start(15)
        tk.Label(self,text='完成后自动进入，无需手动关闭或重启。',font=('Microsoft YaHei UI',10),bg='#0e141b',fg='#bccbd6').pack(anchor='w',padx=28)
        self.protocol('WM_DELETE_WINDOW',self.cancel_startup)
        self.after(100,self.poll)

    def destroy(self):
        try:
            self.bar.stop()
            for timer in self.tk.call('after','info'):
                self.after_cancel(timer)
        except tk.TclError:
            pass
        super().destroy()

    def cancel_startup(self):
        self.cancelled.set()
        write_json(app_updater._data_dir()/'startup_restart_cancelled.json',{'parent_pid':os.getpid(),'cancelled':True})
        self.bar.stop()
        self.destroy()

    def start(self):
        def worker():
            result=startup_check(lambda event:self.events.put(('progress',event)),self.cancelled)
            self.events.put(('done',result))
        threading.Thread(target=worker,daemon=True).start()
        self.mainloop()
        return self.result

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='progress':
                    self.operation.set(value['operation'])
                    percent=value.get('download_percent')
                    if percent is not None:
                        self.bar.stop()
                        self.bar.configure(mode='determinate',value=percent)
                        eta=value.get('remaining_seconds')
                        suffix=f' · 预计剩余 {eta} 秒' if eta is not None else ' · 剩余时间尚不可估算'
                        self.operation.set(f"{value['operation']} · {percent}%{suffix}")
                else:
                    self.result=value
                    self.bar.stop()
                    self.destroy()
                    return
        except queue.Empty:
            self.after(100,self.poll)


def run_before_ui():
    return StartupUpdateWindow().start()
