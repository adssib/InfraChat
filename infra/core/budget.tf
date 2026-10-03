# The last line of defence for the $100 student credit: an email to the subscription's
# owners at half of $5 spent, at $5 spent, and when $5 is forecast. Sessions cost ~$0.03,
# so any of these firing means something was left running.

resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "infrachat-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = 5
  time_grain      = "Monthly"

  time_period {
    start_date = "2026-10-01T00:00:00Z"
  }

  notification {
    operator       = "GreaterThan"
    threshold      = 50
    threshold_type = "Actual"
    contact_roles  = ["Owner"]
  }
  notification {
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Actual"
    contact_roles  = ["Owner"]
  }
  notification {
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Forecasted"
    contact_roles  = ["Owner"]
  }
}
