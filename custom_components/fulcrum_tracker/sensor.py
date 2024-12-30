class FulcrumDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Fulcrum data."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        calendar: ZenPlannerCalendar,
        pr_handler: PRHandler,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=SCAN_INTERVAL,
        )
        self.calendar = calendar
        self.pr_handler = pr_handler
        self._is_initial_load = True
        self._last_full_update = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Fulcrum."""
        try:
            if self._is_initial_load:
                # Do full history fetch on first load
                self.logger.info("🚀 Performing initial full history load...")
                data = await self._fetch_full_history()
                self._is_initial_load = False
                self._last_full_update = datetime.now()
                return data
            else:
                # Do daily update
                self.logger.info("🔍 Performing daily update check...")
                return await self._fetch_daily_update()

        except Exception as err:
            self.logger.error("Error fetching data: %s", err)
            raise

    async def _fetch_full_history(self) -> dict[str, Any]:
        """Fetch complete history."""
        attendance_data = await self.hass.async_add_executor_job(
            self.calendar.get_attendance_data
        )
        pr_data = await self.hass.async_add_executor_job(
            self.pr_handler.get_formatted_prs
        )

        return {
            "total_sessions": attendance_data["total_sessions"],
            "monthly_sessions": attendance_data["monthly_sessions"],
            "last_session": attendance_data["last_session"],
            "recent_prs": pr_data["recent_prs"],
            "total_prs": pr_data["total_prs"],
            "recent_pr_count": pr_data["recent_pr_count"],
            "all_sessions": attendance_data["all_sessions"],
            "pr_details": pr_data["pr_details"],
            "last_update": datetime.now().isoformat(),
        }

    async def _fetch_daily_update(self) -> dict[str, Any]:
        """Fetch just today's data and update existing stats."""
        # Get existing data
        current_data = dict(self.data) if self.data else await self._fetch_full_history()
        
        # Fetch today's data
        today = datetime.now().date()
        today_attendance = await self.hass.async_add_executor_job(
            self.calendar.get_day_attendance,
            today
        )
        today_prs = await self.hass.async_add_executor_job(
            self.pr_handler.get_todays_prs
        )

        # Update stats if we attended today
        if today_attendance.get("attended"):
            current_data["total_sessions"] += 1
            current_data["monthly_sessions"] += 1
            current_data["last_session"] = today.isoformat()
            current_data["all_sessions"].append(today_attendance)
            
            if today_prs:
                current_data["recent_prs"] = today_prs["recent_prs"]
                current_data["total_prs"] = today_prs["total_prs"]
                current_data["recent_pr_count"] = today_prs["recent_pr_count"]
                current_data["pr_details"] = today_prs["pr_details"]

                # Log any PRs with fun messages
                for pr in today_prs.get("pr_details", []):
                    if pr.get("is_pr"):
                        self.logger.info("🎉 NEW PR! %s: %s 💪", pr["name"], pr["value"])

        current_data["last_update"] = datetime.now().isoformat()
        return current_data