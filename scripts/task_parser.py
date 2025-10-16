from schemas.contact_lookup_task import ContactLookupTask

if __name__ == "__main__":
    examples = [
        "find 2025 contact info for Joe's Lawncare in Orlando",
        "get contact info for UCF Computer Science Department",
        "Contact details for BrightSmile Dental 2024 Tampa"
    ]

    for q in examples:
        task = ContactLookupTask.from_raw(q)
        print(task.model_dump())