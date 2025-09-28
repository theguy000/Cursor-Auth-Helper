#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import json
import platform
import re
from datetime import datetime
from colorama import init
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
import logging

init(autoreset=True)

class CursorAccountManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Cursor Account Manager")
        self.root.geometry("900x720")
        self.root.resizable(True, True)

        self.current_account_data = {}
        self.saved_accounts = []
        self.db_path = None

        self.documents_path = self.get_documents_path()
        self.account_data_dir = os.path.join(self.documents_path, "cursor_account_data")
        os.makedirs(self.account_data_dir, exist_ok=True)

        self.executor = ThreadPoolExecutor(max_workers=4)
        self._shutdown_event = threading.Event()
        self._loading_animation = 0
        self._stop_animation = False

        self.init_database_path()
        self.setup_ui()
        self.load_saved_accounts()

        # Delay initial refresh to avoid blocking UI startup
        self.root.after(100, self.refresh_account_info)

    def set_buttons_state(self, enabled):
        state = "normal" if enabled else "disabled"
        try:
            for widget in self.root.winfo_children():
                if isinstance(widget, ttk.Frame):
                    for child in widget.winfo_children():
                        if isinstance(child, ttk.Frame):
                            for button in child.winfo_children():
                                if isinstance(button, ttk.Button):
                                    button.configure(state=state)
        except:
            pass

    def show_loading_animation(self, base_message):
        if not self._shutdown_event.is_set() and not self._stop_animation:
            dots = "." * ((self._loading_animation % 4))
            self.status_var.set(f"{base_message}{dots}")
            self._loading_animation += 1
            self.root.after(500, lambda: self.show_loading_animation(base_message))

    def get_proxy(self):
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy:
            return {"http": proxy, "https": proxy}
        return None

    def get_token_from_cursor_config(self):
        """Get token using integrated token retrieval methods"""
        try:
            # Try fallback token retrieval methods from multiple sources
            system = platform.system()
            
            # Determine paths based on system
            if system == "Windows":
                storage_path = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Cursor", "User", "globalStorage", "storage.json")
                session_path = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Cursor", "Session Storage")
            elif system == "Darwin":  # macOS
                storage_path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Cursor", "User", "globalStorage", "storage.json")
                session_path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Cursor", "Session Storage")
            else:  # Linux
                storage_path = os.path.join(os.path.expanduser("~"), ".config", "Cursor", "User", "globalStorage", "storage.json")
                session_path = os.path.join(os.path.expanduser("~"), ".config", "Cursor", "Session Storage")
            
            # Try to get token from storage.json first
            token = self._get_token_from_storage(storage_path)
            if token:
                return token
                
            # Try to get token from sqlite database (already implemented in existing method)
            token = self._get_token_from_sqlite()
            if token:
                return token
                
            # Try to get token from session storage as last resort
            token = self._get_token_from_session(session_path)
            if token:
                return token
                
            return None
            
        except Exception as e:
            logging.error(f"Error getting token from cursor config: {e}")
            return None
    
    def _get_token_from_storage(self, storage_path):
        """Get token from storage.json"""
        if not os.path.exists(storage_path):
            return None
            
        try:
            with open(storage_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                # Try to get accessToken
                if 'cursorAuth/accessToken' in data:
                    return data['cursorAuth/accessToken']
                
                # Try other possible keys
                for key in data:
                    if 'token' in key.lower() and isinstance(data[key], str) and len(data[key]) > 20:
                        return data[key]
        except Exception as e:
            logging.error(f"Get token from storage.json failed: {e}")
        
        return None
    
    def _get_token_from_sqlite(self):
        """Get token from sqlite database using existing connection method"""
        try:
            conn = self.connect_to_database()
            if not conn:
                return None
                
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM ItemTable WHERE key LIKE '%token%'")
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                try:
                    value = row[0]
                    if isinstance(value, str) and len(value) > 20:
                        return value
                    # Try to parse JSON
                    data = json.loads(value)
                    if isinstance(data, dict) and 'token' in data:
                        return data['token']
                except:
                    continue
        except Exception as e:
            logging.error(f"Get token from sqlite failed: {e}")
        
        return None
    
    def _get_token_from_session(self, session_path):
        """Get token from session storage"""
        if not os.path.exists(session_path):
            return None
            
        try:
            # Try to find all possible session files
            for file in os.listdir(session_path):
                if file.endswith('.log'):
                    file_path = os.path.join(session_path, file)
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read().decode('utf-8', errors='ignore')
                            # Find token pattern
                            token_match = re.search(r'"token":"([^"]+)"', content)
                            if token_match:
                                return token_match.group(1)
                    except:
                        continue
        except Exception as e:
            logging.error(f"Get token from session failed: {e}")
        
        return None

    def get_usage_info(self, token):
        url = "https://www.cursor.com/api/usage"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": f"WorkosCursorSessionToken=user_01OOOOOOOOOOOOOOOOOOOOOOOO%3A%3A{token}"
        }

        try:
            proxies = self.get_proxy()
            response = requests.get(url, headers=headers, timeout=10, proxies=proxies)
            response.raise_for_status()
            data = response.json()

            # Get Premium usage and limit
            gpt4_data = data.get("gpt-4", {})
            premium_usage = gpt4_data.get("numRequestsTotal", 0)
            max_premium_usage = gpt4_data.get("maxRequestUsage", 999)

            # Get Basic usage
            gpt35_data = data.get("gpt-3.5-turbo", {})
            basic_usage = gpt35_data.get("numRequestsTotal", 0)

            return {
                'premium_usage': premium_usage,
                'max_premium_usage': max_premium_usage,
                'basic_usage': basic_usage,
                'max_basic_usage': "No Limit"
            }
        except requests.RequestException as e:
            # Log detailed error information for debugging
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Get usage info failed: {str(e)} (Status: {e.response.status_code})")
                if e.response.status_code == 401:
                    logging.error("Authentication token may be invalid or expired. Please re-authenticate with Cursor.")
            else:
                logging.error(f"Get usage info failed: {str(e)}")
            return None
        except Exception as e:
            logging.error(f"Get usage info failed: {str(e)}")
            return None

    def get_stripe_profile(self, token):
        """Get user subscription info from Cursor API"""
        url = "https://api2.cursor.sh/auth/full_stripe_profile"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        try:
            proxies = self.get_proxy()
            response = requests.get(url, headers=headers, timeout=10, proxies=proxies)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Get subscription info failed: {str(e)}")
            return None
        except Exception as e:
            logging.error(f"Get subscription info failed: {str(e)}")
            return None

    def format_subscription_type(self, subscription_data):
        """Format subscription type from API response"""
        if not subscription_data:
            return "Free"

        # Handle new API response format
        if "membershipType" in subscription_data:
            membership_type = subscription_data.get("membershipType", "").lower()
            subscription_status = subscription_data.get("subscriptionStatus", "").lower()

            if subscription_status == "active":
                if membership_type == "pro":
                    return "Pro"
                elif membership_type == "free_trial":
                    return "Free Trial"
                elif membership_type == "pro_trial":
                    return "Pro Trial"
                elif membership_type == "team":
                    return "Team"
                elif membership_type == "enterprise":
                    return "Enterprise"
                elif membership_type:
                    return membership_type.capitalize()
                else:
                    return "Active Subscription"
            elif subscription_status:
                return f"{membership_type.capitalize()} ({subscription_status})"

        # Compatible with old API response format
        subscription = subscription_data.get("subscription")
        if subscription:
            plan = subscription.get("plan", {}).get("nickname", "Unknown")
            status = subscription.get("status", "unknown")

            if status == "active":
                if "pro" in plan.lower():
                    return "Pro"
                elif "pro_trial" in plan.lower():
                    return "Pro Trial"
                elif "free_trial" in plan.lower():
                    return "Free Trial"
                elif "team" in plan.lower():
                    return "Team"
                elif "enterprise" in plan.lower():
                    return "Enterprise"
                else:
                    return plan
            else:
                return f"{plan} ({status})"

        return "Free"

    def get_documents_path(self):
        """Get the Documents folder path for the current OS"""
        system = platform.system().lower()

        if system == "windows":
            return os.path.join(os.path.expanduser("~"), "Documents")
        elif system == "darwin":  # macOS
            return os.path.join(os.path.expanduser("~"), "Documents")
        else:  # Linux and others
            return os.path.join(os.path.expanduser("~"), "Documents")

    def init_database_path(self):
        system = platform.system().lower()

        if system == "windows":
            self.db_path = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Cursor", "User", "globalStorage", "state.vscdb")
        elif system == "darwin":
            self.db_path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Cursor", "User", "globalStorage", "state.vscdb")
        else:
            self.db_path = os.path.join(os.path.expanduser("~"), ".config", "Cursor", "User", "globalStorage", "state.vscdb")

    def setup_ui(self):
        """Setup the user interface"""
        # Configure main window
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create main frame with padding
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

        # Warning frame at the top
        self.setup_warning_frame(main_frame)

        # Account info frame
        self.setup_account_info_frame(main_frame)

        # Control buttons frame
        self.setup_control_buttons(main_frame)

        # Saved accounts frame
        self.setup_saved_accounts_frame(main_frame)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready - Click 'Refresh' to load current account information")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var,
                              relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=11, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(20, 0))

    def setup_warning_frame(self, parent):
        """Setup the warning frame at the top"""
        warning_frame = tk.Frame(parent, bg="#fff3cd", relief=tk.RAISED, bd=2)
        warning_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        warning_frame.columnconfigure(1, weight=1)
        
        # Warning icon
        warning_label = tk.Label(warning_frame, text="⚠️", bg="#fff3cd", fg="#856404", font=("Arial", 16, "bold"))
        warning_label.grid(row=0, column=0, padx=(10, 5), pady=10, sticky=tk.W)
        
        # Warning text
        warning_text = tk.Label(warning_frame, 
                               text="IMPORTANT: Do NOT logout from Cursor directly! Always use the 'Logout' button in this application, otherwise your token will become invalid for this account manager.",
                               bg="#fff3cd", fg="#856404", font=("Arial", 10, "bold"), wraplength=700, justify=tk.LEFT)
        warning_text.grid(row=0, column=1, padx=(5, 10), pady=10, sticky=(tk.W, tk.E))

    def setup_account_info_frame(self, parent):
        """Setup the account information display frame"""
        info_frame = ttk.LabelFrame(parent, text="Current Account Information", padding="15")
        info_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        info_frame.columnconfigure(1, weight=1)

        # Email
        ttk.Label(info_frame, text="Email:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.email_var = tk.StringVar()
        email_entry = ttk.Entry(info_frame, textvariable=self.email_var, state="readonly", width=50)
        email_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=2)

        # Account Type
        ttk.Label(info_frame, text="Account Type:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        self.account_type_var = tk.StringVar()
        account_type_entry = ttk.Entry(info_frame, textvariable=self.account_type_var, state="readonly", width=50)
        account_type_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=2)

        # Membership Type
        ttk.Label(info_frame, text="Membership:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky=tk.W, padx=(0, 10))
        self.membership_var = tk.StringVar()
        membership_entry = ttk.Entry(info_frame, textvariable=self.membership_var, state="readonly", width=50)
        membership_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=2)

        # Trial Status
        ttk.Label(info_frame, text="Trial Status:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky=tk.W, padx=(0, 10))
        self.trial_status_var = tk.StringVar()
        trial_status_entry = ttk.Entry(info_frame, textvariable=self.trial_status_var, state="readonly", width=50)
        trial_status_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=2)

        # Pro Trial Remaining
        ttk.Label(info_frame, text="Pro Trial Remaining:", font=("Arial", 10, "bold")).grid(row=4, column=0, sticky=tk.W, padx=(0, 10))
        self.pro_trial_var = tk.StringVar()
        pro_trial_entry = ttk.Entry(info_frame, textvariable=self.pro_trial_var, state="readonly", width=50)
        pro_trial_entry.grid(row=4, column=1, sticky=(tk.W, tk.E), pady=2)

        # Last Updated
        ttk.Label(info_frame, text="Last Updated:", font=("Arial", 10, "bold")).grid(row=5, column=0, sticky=tk.W, padx=(0, 10))
        self.last_updated_var = tk.StringVar()
        last_updated_entry = ttk.Entry(info_frame, textvariable=self.last_updated_var, state="readonly", width=50)
        last_updated_entry.grid(row=5, column=1, sticky=(tk.W, tk.E), pady=2)

    def setup_control_buttons(self, parent):
        button_frame = ttk.Frame(parent)
        button_frame.grid(row=2, column=0, pady=(0, 15))

        # Create buttons with consistent icon and text alignment using emoji variants
        ttk.Button(button_frame, text="🔄 Refresh", command=self.refresh_account_info).grid(row=0, column=0, padx=(0, 10), sticky='ew')
        ttk.Button(button_frame, text="💾 Save Account", command=self.save_current_account).grid(row=0, column=1, padx=(0, 10), sticky='ew')
        ttk.Button(button_frame, text="⚙️ Manual Input", command=self.manual_input_dialog).grid(row=0, column=2, padx=(0, 10), sticky='ew')
        ttk.Button(button_frame, text="📤 Export Data", command=self.export_account_data).grid(row=0, column=3, padx=(0, 10), sticky='ew')
        ttk.Button(button_frame, text="🚪 Logout", command=self.logout_current_account).grid(row=0, column=4, padx=(0, 10), sticky='ew')
        
        # Configure button frame columns to have equal weight for consistent sizing
        for i in range(5):
            button_frame.columnconfigure(i, weight=1)

    def setup_saved_accounts_frame(self, parent):
        """Setup saved accounts management frame"""
        saved_frame = ttk.LabelFrame(parent, text="Saved Accounts", padding="15")
        saved_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        saved_frame.columnconfigure(0, weight=1)
        saved_frame.rowconfigure(0, weight=1)

        # Create treeview for saved accounts
        columns = ("email", "type", "membership", "saved_date")
        self.accounts_tree = ttk.Treeview(saved_frame, columns=columns, show="headings", height=8)

        # Configure column headings
        self.accounts_tree.heading("email", text="Email")
        self.accounts_tree.heading("type", text="Account Type")
        self.accounts_tree.heading("membership", text="Membership")
        self.accounts_tree.heading("saved_date", text="Saved Date")

        # Configure column widths
        self.accounts_tree.column("email", width=200)
        self.accounts_tree.column("type", width=100)
        self.accounts_tree.column("membership", width=120)
        self.accounts_tree.column("saved_date", width=150)

        self.accounts_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure tags for styling failed accounts
        self.accounts_tree.tag_configure("failed", background="#ffcccc", foreground="#cc0000")
        self.accounts_tree.tag_configure("normal", background="white", foreground="black")

        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(saved_frame, orient="vertical", command=self.accounts_tree.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.accounts_tree.configure(yscrollcommand=scrollbar.set)

        # Buttons for saved accounts
        saved_buttons_frame = ttk.Frame(saved_frame)
        saved_buttons_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        ttk.Button(saved_buttons_frame, text="↺ Restore Selected", command=self.restore_selected_account).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(saved_buttons_frame, text="✕ Delete Selected", command=self.delete_selected_account).grid(row=0, column=1, padx=(0, 10))

        # Refresh saved accounts button at the bottom
        refresh_frame = ttk.Frame(saved_frame)
        refresh_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0))

        ttk.Button(refresh_frame, text="↻ Refresh Saved Accounts", command=self.refresh_saved_accounts).pack()

    def connect_to_database(self):
        if not self.db_path or not os.path.exists(self.db_path):
            return None
        try:
            return sqlite3.connect(self.db_path)
        except:
            return None

    def refresh_account_info(self):
        self._loading_animation = 0
        self._stop_animation = False
        self.show_loading_animation("Refreshing account information")
        self.set_buttons_state(False)

        future = self.executor.submit(self._refresh_account_info_worker)
        self.root.after(100, lambda: self._check_refresh_future(future))

    def _refresh_account_info_worker(self):
        try:
            conn = self.connect_to_database()
            if not conn:
                return {"error": "Cannot connect to Cursor database. Make sure Cursor is installed and has been run at least once."}

            try:
                cursor = conn.cursor()
                account_data = {}

                keys_to_get = [
                    "cursorAuth/cachedEmail",
                    "cursorAuth/refreshToken",
                    "cursorAuth/accessToken",
                    "cursorAuth/cachedSignUpType",
                    "cursorAuth/stripeMembershipType"
                ]

                for key in keys_to_get:
                    cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
                    result = cursor.fetchone()
                    if result:
                        account_data[key] = result[0]

                conn.close()

                # Try to get token using cursor_acc_info approach first
                access_token = self.get_token_from_cursor_config()

                # Fallback to database token if cursor_acc_info approach fails
                if not access_token:
                    access_token = account_data.get("cursorAuth/accessToken") or account_data.get("cursorAuth/refreshToken")

                if not access_token:
                    return {"error": "No access token found. Please login to Cursor first."}

                subscription_info = self.get_stripe_profile(access_token)

                return {
                    "success": True,
                    "data": account_data,
                    "subscription_info": subscription_info
                }

            except sqlite3.Error as e:
                return {"error": f"Database error: {e}"}

        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

    def _check_refresh_future(self, future):
        """Check if refresh operation is complete"""
        if future.done():
            try:
                result = future.result()

                if "error" in result:
                    self.status_var.set(f"Error: {result['error']}")
                    messagebox.showerror("Database Error", result["error"])
                else:
                    # Update UI with retrieved data
                    self.update_ui_with_account_data(
                        result["data"],
                        result.get("subscription_info")
                    )

                    # Store current account data
                    self.current_account_data = result["data"]

                    self.status_var.set("Account information and subscription status refreshed successfully")

            except Exception as e:
                self.status_var.set(f"Error: {e}")
                messagebox.showerror("Error", f"Unexpected error: {e}")
            finally:
                # Stop animation and re-enable buttons
                self._stop_animation = True
                self.set_buttons_state(True)
        else:
            # Check again in 100ms
            self.root.after(100, lambda: self._check_refresh_future(future))

    def update_ui_with_account_data(self, account_data, subscription_info=None):
        """Update UI with account data and subscription info"""
        # Email
        email = account_data.get("cursorAuth/cachedEmail", "Not found")
        self.email_var.set(email)

        # Account Type
        account_type = account_data.get("cursorAuth/cachedSignUpType", "Not found")
        self.account_type_var.set(account_type)

        # Membership Type - prefer live API data over stored data
        if subscription_info:
            membership = self.format_subscription_type(subscription_info)
            self.membership_var.set(membership)

            # Show trial status
            membership_type = subscription_info.get("membershipType", "").lower()
            if "trial" in membership_type:
                days_remaining = subscription_info.get("daysRemainingOnTrial")
                if days_remaining is not None and days_remaining > 0:
                    self.trial_status_var.set(f"Active - {days_remaining} days remaining")
                    self.pro_trial_var.set(f"{days_remaining} days remaining")
                else:
                    self.trial_status_var.set("Trial (checking...)")
                    self.pro_trial_var.set("Checking...")
            else:
                self.trial_status_var.set("Not on trial")
                self.pro_trial_var.set("Not applicable")
        else:
            # Fallback to stored data
            membership = account_data.get("cursorAuth/stripeMembershipType", "Not found")
            self.membership_var.set(membership)
            self.trial_status_var.set("Unable to fetch live data")
            self.pro_trial_var.set("Unable to fetch")

        # Usage information removed as requested

        # Last updated
        self.last_updated_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def save_current_account(self):
        """Save current account information to file (threaded)"""
        if not self.current_account_data:
            messagebox.showwarning("No Data", "No account information to save. Please refresh first.")
            return

        self.status_var.set("Saving account information...")
        self.root.update()

        # Disable buttons during operation
        self.set_buttons_state(False)

        # Prepare account data for saving
        save_data = {
            "email": self.email_var.get(),
            "account_type": self.account_type_var.get(),
            "membership": self.membership_var.get(),
            "trial_status": self.trial_status_var.get(),
            "pro_trial_remaining": self.pro_trial_var.get(),
            "saved_date": datetime.now().isoformat(),
            "raw_data": self.current_account_data
        }

        # Run in thread to prevent UI freezing
        future = self.executor.submit(self._save_account_worker, save_data)
        self.root.after(100, lambda: self._check_save_future(future))

    def _save_account_worker(self, save_data):
        """Worker method for saving account"""
        try:
            # Generate filename
            email = save_data["email"].replace("@", "_").replace(".", "_")
            filename = f"cursor_account_{email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(self.account_data_dir, filename)

            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2)

            return {"success": True, "filename": filename, "filepath": filepath}

        except Exception as e:
            return {"error": f"Error saving account: {e}"}

    def _check_save_future(self, future):
        """Check if save operation is complete"""
        if future.done():
            try:
                result = future.result()

                if "error" in result:
                    self.status_var.set(result["error"])
                    messagebox.showerror("Save Error", result["error"])
                else:
                    self.status_var.set(f"Account saved to: {result['filename']}")
                    messagebox.showinfo("Success", f"Account information saved to:\n{result['filepath']}")

                    # Reload saved accounts list
                    self.load_saved_accounts()

            except Exception as e:
                self.status_var.set(f"Error: {e}")
                messagebox.showerror("Error", f"Unexpected error: {e}")
            finally:
                # Re-enable buttons
                self.set_buttons_state(True)
        else:
            # Check again in 100ms
            self.root.after(100, lambda: self._check_save_future(future))

    def load_saved_accounts(self):
        """Load saved accounts from files (startup only)"""
        for item in self.accounts_tree.get_children():
            self.accounts_tree.delete(item)

        self.saved_accounts = []

        try:
            json_files = [f for f in os.listdir(self.account_data_dir) if f.endswith('.json')]

            for filename in json_files:
                filepath = os.path.join(self.account_data_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        account_data = json.load(f)

                    self.saved_accounts.append(account_data)

                    self.accounts_tree.insert("", "end", values=(
                        account_data.get("email", "Unknown"),
                        account_data.get("account_type", "Unknown"),
                        account_data.get("membership", "Unknown"),
                        account_data.get("saved_date", "Unknown")[:19]
                    ), tags=("normal",))

                except Exception as e:
                    print(f"Error loading {filename}: {e}")

        except Exception as e:
            print(f"Error loading saved accounts: {e}")

    def refresh_saved_accounts(self):
        """Refresh all saved accounts with live subscription and usage data"""
        self._loading_animation = 0
        self._stop_animation = False
        self.show_loading_animation("Refreshing saved accounts subscription data")
        self.set_buttons_state(False)

        future = self.executor.submit(self._refresh_saved_accounts_worker)
        self.root.after(100, lambda: self._check_refresh_saved_future(future))

    def _refresh_saved_accounts_worker(self):
        """Worker method for refreshing saved accounts"""
        try:
            # First load all saved accounts
            json_files = [f for f in os.listdir(self.account_data_dir) if f.endswith('.json')]
            if not json_files:
                return {"error": "No saved accounts found"}

            refreshed_accounts = []
            updated_tree_data = []
            failed_accounts = []  # Track which accounts failed to refresh
            total_accounts = len(json_files)
            processed = 0

            for filename in json_files:
                filepath = os.path.join(self.account_data_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        account_data = json.load(f)

                    # Get token from raw_data
                    raw_data = account_data.get("raw_data", {})
                    access_token = (raw_data.get("cursorAuth/accessToken") or
                                  raw_data.get("cursorAuth/refreshToken"))

                    if access_token:
                        # Get fresh subscription data
                        subscription_info = self.get_stripe_profile(access_token)

                        # Check if API call failed (subscription_info is None)
                        if subscription_info is None:
                            # Mark as failed due to API error (401, etc.)
                            account_data["membership"] = "API Error - Auth Failed"
                            failed_accounts.append(len(updated_tree_data))
                            updated_tree_data.append((
                                account_data.get("email", "Unknown"),
                                account_data.get("account_type", "Unknown"),
                                "API Error - Auth Failed",
                                account_data.get("saved_date", "Unknown")[:19],
                                True  # Failed
                            ))
                            refreshed_accounts.append(account_data)
                            continue

                        # Update account data with fresh info
                        if subscription_info:
                            membership = self.format_subscription_type(subscription_info)
                            account_data["membership"] = membership

                            membership_type = subscription_info.get("membershipType", "").lower()
                            if "trial" in membership_type:
                                days_remaining = subscription_info.get("daysRemainingOnTrial")
                                if days_remaining is not None and days_remaining > 0:
                                    account_data["trial_status"] = f"Active - {days_remaining} days remaining"
                                    account_data["pro_trial_remaining"] = f"{days_remaining} days remaining"
                                else:
                                    account_data["trial_status"] = "Trial expired"
                                    account_data["pro_trial_remaining"] = "Expired"
                            else:
                                account_data["trial_status"] = "Not on trial"
                                account_data["pro_trial_remaining"] = "Not applicable"

                        # Usage information removed as requested

                        # Save updated data back to file
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(account_data, f, indent=2)
                    else:
                        # No access token found - mark as failed
                        account_data["membership"] = "No Token Found"
                        failed_accounts.append(len(updated_tree_data))
                        updated_tree_data.append((
                            account_data.get("email", "Unknown"),
                            account_data.get("account_type", "Unknown"),
                            "No Token Found",
                            account_data.get("saved_date", "Unknown")[:19],
                            True  # Failed
                        ))
                        refreshed_accounts.append(account_data)
                        continue

                    refreshed_accounts.append(account_data)

                    # Prepare updated tree data (successful refresh)
                    updated_tree_data.append((
                        account_data.get("email", "Unknown"),
                        account_data.get("account_type", "Unknown"),
                        account_data.get("membership", "Unknown"),
                        account_data.get("saved_date", "Unknown")[:19],
                        False  # Not failed
                    ))

                    processed += 1

                except Exception as e:
                    print(f"Error refreshing {filename}: {e}")
                    # Still include the account even if refresh failed
                    if 'account_data' in locals():
                        refreshed_accounts.append(account_data)
                        failed_accounts.append(len(updated_tree_data))  # Track index of failed account
                        updated_tree_data.append((
                            account_data.get("email", "Unknown"),
                            account_data.get("account_type", "Unknown"),
                            account_data.get("membership", "Refresh failed"),
                            account_data.get("saved_date", "Unknown")[:19],
                            True  # Failed
                        ))
                    continue

            return {
                "success": True,
                "accounts": refreshed_accounts,
                "tree_data": updated_tree_data,
                "failed_accounts": failed_accounts,
                "total": total_accounts,
                "processed": processed
            }

        except Exception as e:
            return {"error": f"Error refreshing saved accounts: {e}"}

    def _check_refresh_saved_future(self, future):
        """Check if refresh saved accounts operation is complete"""
        if future.done():
            try:
                result = future.result()

                if "error" in result:
                    self.status_var.set(result["error"])
                    messagebox.showerror("Refresh Error", result["error"])
                else:
                    # Clear existing items
                    for item in self.accounts_tree.get_children():
                        self.accounts_tree.delete(item)

                    # Update data
                    self.saved_accounts = result["accounts"]

                    # Add to treeview with fresh data and styling
                    for tree_data in result["tree_data"]:
                        # tree_data now includes a 5th element indicating if failed
                        display_data = tree_data[:4]  # Only show first 4 elements
                        is_failed = tree_data[4] if len(tree_data) > 4 else False

                        tag = "failed" if is_failed else "normal"
                        self.accounts_tree.insert("", "end", values=display_data, tags=(tag,))

                    total = result["total"]
                    processed = result["processed"]
                    self.status_var.set(f"Refreshed {processed}/{total} saved accounts with live subscription data")

                    messagebox.showinfo("Accounts Refreshed",
                                       f"Successfully refreshed {processed}/{total} saved accounts\nwith current subscription and usage data!")

            except Exception as e:
                self.status_var.set(f"Error: {e}")
                messagebox.showerror("Error", f"Unexpected error: {e}")
            finally:
                # Stop animation and re-enable buttons
                self._stop_animation = True
                self.set_buttons_state(True)
        else:
            # Check again in 100ms
            self.root.after(100, lambda: self._check_refresh_saved_future(future))

    def restore_selected_account(self):
        """Restore selected account to Cursor database"""
        selection = self.accounts_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select an account to restore.")
            return

        # Get selected account data
        item = selection[0]
        index = self.accounts_tree.index(item)
        account_data = self.saved_accounts[index]

        # Confirm restore
        email = account_data.get("email", "Unknown")
        if not messagebox.askyesno("Confirm Restore", f"Restore account '{email}' to Cursor?\nThis will overwrite current account information."):
            return

        try:
            # Connect to database and update
            conn = self.connect_to_database()
            if not conn:
                messagebox.showerror("Database Error", "Cannot connect to Cursor database.")
                return

            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")

            try:
                raw_data = account_data.get("raw_data", {})

                for key, value in raw_data.items():
                    # Check if key exists
                    cursor.execute("SELECT COUNT(*) FROM ItemTable WHERE key = ?", (key,))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
                    else:
                        cursor.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))

                cursor.execute("COMMIT")

                messagebox.showinfo("Success", f"Account '{email}' restored successfully!\nRestart Cursor to see changes.")
                self.status_var.set(f"Account '{email}' restored successfully")

                # Refresh current account info
                self.refresh_account_info()

            except Exception as e:
                cursor.execute("ROLLBACK")
                raise e

        except Exception as e:
            messagebox.showerror("Restore Error", f"Error restoring account: {e}")
            self.status_var.set(f"Error restoring account: {e}")
        finally:
            if conn:
                conn.close()

    def delete_selected_account(self):
        """Delete selected saved account"""
        selection = self.accounts_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select an account to delete.")
            return

        # Get selected account data
        item = selection[0]
        index = self.accounts_tree.index(item)
        account_data = self.saved_accounts[index]

        email = account_data.get("email", "Unknown")
        if not messagebox.askyesno("Confirm Delete", f"Delete saved account '{email}'?\nThis action cannot be undone."):
            return

        try:
            # Find and delete the file
            saved_date = account_data.get("saved_date", "")
            json_files = [f for f in os.listdir(self.account_data_dir) if f.endswith('.json')]

            for filename in json_files:
                filepath = os.path.join(self.account_data_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if (data.get("email") == email and
                        data.get("saved_date") == saved_date):
                        os.remove(filepath)
                        messagebox.showinfo("Success", f"Account '{email}' deleted successfully.")
                        self.load_saved_accounts()
                        return

                except Exception:
                    continue

            messagebox.showwarning("Not Found", "Could not find the account file to delete.")

        except Exception as e:
            messagebox.showerror("Delete Error", f"Error deleting account: {e}")

    def manual_input_dialog(self):
        """Open manual input dialog for account information"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Manual Account Input")
        
        # Make dialog modal
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Get screen dimensions
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        
        # Calculate dialog size (responsive to screen size)
        dialog_width = min(600, int(screen_width * 0.8))
        dialog_height = min(500, int(screen_height * 0.8))
        
        # Calculate position to center the dialog on screen
        x = (screen_width - dialog_width) // 2
        y = (screen_height - dialog_height) // 2
        
        # Ensure dialog stays within screen bounds
        x = max(0, min(x, screen_width - dialog_width))
        y = max(0, min(y, screen_height - dialog_height))
        
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        dialog.resizable(True, True)
        dialog.minsize(400, 350)  # Set minimum size to ensure usability

        # Create a canvas and scrollbar for better content management
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        main_frame = ttk.Frame(scrollable_frame, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Input fields
        ttk.Label(main_frame, text="Manual Account Input", font=("Arial", 14, "bold")).pack(pady=(0, 20))

        # Email
        ttk.Label(main_frame, text="Email:").pack(anchor=tk.W)
        email_entry = ttk.Entry(main_frame)
        email_entry.pack(fill=tk.X, pady=(0, 10))

        # Access Token
        ttk.Label(main_frame, text="Access Token:").pack(anchor=tk.W)
        access_token_text = tk.Text(main_frame, height=4, wrap=tk.WORD)
        access_token_text.pack(fill=tk.X, pady=(0, 10))

        # Refresh Token
        ttk.Label(main_frame, text="Refresh Token:").pack(anchor=tk.W)
        refresh_token_text = tk.Text(main_frame, height=4, wrap=tk.WORD)
        refresh_token_text.pack(fill=tk.X, pady=(0, 10))

        # Account Type
        ttk.Label(main_frame, text="Account Type:").pack(anchor=tk.W)
        account_type_var = tk.StringVar(value="Auth_0")
        account_type_combo = ttk.Combobox(main_frame, textvariable=account_type_var,
                                         values=["Auth_0", "Google", "GitHub"], state="readonly")
        account_type_combo.pack(fill=tk.X, pady=(0, 20))

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack()

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Cleanup mousewheel binding when dialog is closed
        def on_dialog_close():
            canvas.unbind_all("<MouseWheel>")
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)

        def apply_manual_input():
            email = email_entry.get().strip()
            access_token = access_token_text.get("1.0", tk.END).strip()
            refresh_token = refresh_token_text.get("1.0", tk.END).strip()
            account_type = account_type_var.get()

            if not email:
                messagebox.showwarning("Invalid Input", "Email is required.")
                return

            if not access_token or not refresh_token:
                messagebox.showwarning("Invalid Input", "Both access token and refresh token are required.")
                return

            # Apply to database
            try:
                conn = self.connect_to_database()
                if not conn:
                    messagebox.showerror("Database Error", "Cannot connect to Cursor database.")
                    return

                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION")

                updates = [
                    ("cursorAuth/cachedEmail", email),
                    ("cursorAuth/accessToken", access_token),
                    ("cursorAuth/refreshToken", refresh_token),
                    ("cursorAuth/cachedSignUpType", account_type)
                ]

                for key, value in updates:
                    cursor.execute("SELECT COUNT(*) FROM ItemTable WHERE key = ?", (key,))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (key, value))
                    else:
                        cursor.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (value, key))

                cursor.execute("COMMIT")
                conn.close()

                messagebox.showinfo("Success", "Account information updated successfully!\nRestart Cursor to see changes.")
                on_dialog_close()

                # Refresh main window
                self.refresh_account_info()

            except Exception as e:
                messagebox.showerror("Error", f"Error updating account: {e}")

        ttk.Button(button_frame, text="Apply", command=apply_manual_input).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="Cancel", command=on_dialog_close).pack(side=tk.LEFT)

    def export_account_data(self):
        """Export current account data to JSON file"""
        if not self.current_account_data:
            messagebox.showwarning("No Data", "No account information to export. Please refresh first.")
            return

        # Ask user for save location
        filename = filedialog.asksaveasfilename(
            title="Export Account Data",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=f"cursor_account_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        if not filename:
            return

        try:
            export_data = {
                "export_date": datetime.now().isoformat(),
                "email": self.email_var.get(),
                "account_type": self.account_type_var.get(),
                "membership": self.membership_var.get(),
                "trial_status": self.trial_status_var.get(),
                "raw_data": self.current_account_data
            }

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2)

            messagebox.showinfo("Success", f"Account data exported to:\n{filename}")
            self.status_var.set(f"Account data exported successfully")

        except Exception as e:
            messagebox.showerror("Export Error", f"Error exporting data: {e}")

    def logout_current_account(self):
        """Logout current account by clearing authentication data from Cursor database"""
        if not messagebox.askyesno("Confirm Logout", "Logout current account?\nThis will remove authentication data from Cursor."):
            return

        try:
            conn = self.connect_to_database()
            if not conn:
                messagebox.showerror("Database Error", "Cannot connect to Cursor database.")
                return

            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")

            try:
                # Remove authentication keys
                auth_keys = [
                    "cursorAuth/cachedEmail",
                    "cursorAuth/refreshToken", 
                    "cursorAuth/accessToken",
                    "cursorAuth/cachedSignUpType",
                    "cursorAuth/stripeMembershipType"
                ]

                for key in auth_keys:
                    cursor.execute("DELETE FROM ItemTable WHERE key = ?", (key,))

                cursor.execute("COMMIT")
                conn.close()

                # Clear UI fields
                self.email_var.set("")
                self.account_type_var.set("")
                self.membership_var.set("")
                self.trial_status_var.set("")
                self.pro_trial_var.set("")
                self.last_updated_var.set("")
                self.current_account_data = {}

                messagebox.showinfo("Success", "Account logged out successfully!\nRestart Cursor to see changes.")
                self.status_var.set("Account logged out successfully")

            except Exception as e:
                cursor.execute("ROLLBACK")
                raise e

        except Exception as e:
            messagebox.showerror("Logout Error", f"Error logging out account: {e}")
            self.status_var.set(f"Error logging out account: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

def main():
    """Main function to run the application"""
    root = tk.Tk()
    app = CursorAccountManager(root)

    # Handle window closing
    def on_closing():
        # Shutdown thread pool gracefully
        app._shutdown_event.set()
        app.executor.shutdown(wait=False)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Set window icon (if available)
    try:
        # You can add an icon file here if you have one
        pass
    except:
        pass

    root.mainloop()

if __name__ == "__main__":
    main()
